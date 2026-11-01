"""Minimal production models, preparation jobs, asset and story API."""

import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import media, story
from .assets import valid_url
from .timeline import kept_ranges, validate_intervals


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Overlay(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    asset_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    asset_in: float = Field(default=0, ge=0)
    layout: Literal["top", "bottom", "full"] = "top"
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    width: float | None = Field(default=None, ge=0.01, le=1)
    height: float | None = Field(default=None, ge=0.01, le=1)
    white_nits: float = Field(default=203, ge=100, le=1000)
    enabled: bool = True
    audio: bool = False
    volume: float = Field(default=0.4, ge=0, le=1)
    purpose: str = Field(default="", max_length=2000)


class Punch(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    scale: float = Field(default=1.1, ge=1, le=1.3)
    enabled: bool = True


class Music(Strict):
    asset_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    volume: float = Field(default=0.12, ge=0, le=0.5)
    offset: float = Field(default=0, ge=0)
    duck: bool = True
    enabled: bool = True


class StoryPlan(Strict):
    topic: str = Field(default="", max_length=500)
    hook: str = Field(default="", max_length=1000)
    hook_reason: str = Field(default="", max_length=2000)
    cta: str = Field(default="", max_length=1000)
    app_bundle_id: str = Field(default="", max_length=200)


class PrepareOptions(Strict):
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    minimum_pause: float = Field(default=0.12, ge=0.06, le=5)
    padding: float = Field(default=0.025, ge=0.01, le=0.6)
    choose_retakes: bool = True
    max_words: int = Field(default=3, ge=1, le=3)
    remove_fillers: bool = True


class TakeDecision(Strict):
    selected: int | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)


class AssetImport(Strict):
    path: str
    name: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2000)
    source_kind: Literal["local", "web", "simulator", "download"] = "local"
    description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    rights: str = Field(default="", max_length=4000)


class AssetMetadata(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    rights: str = Field(default="", max_length=4000)


class HookEntry(Strict):
    text: str = Field(min_length=1, max_length=1000)
    topic: str = Field(default="", max_length=500)
    source_url: str = Field(default="", max_length=2000)
    views: int | None = Field(default=None, ge=0)
    retention: float | None = Field(default=None, ge=0, le=1)
    notes: str = Field(default="", max_length=2000)


class FetchAsset(Strict):
    url: str = Field(max_length=2000)
    kind: Literal["audio", "video"] = "audio"
    tags: list[str] = Field(default_factory=list, max_length=50)
    rights: str = Field(default="", max_length=4000)


class CaptureApp(Strict):
    mode: Literal["screenshot", "video"] = "screenshot"
    seconds: float = Field(default=4, ge=1, le=30)
    description: str = Field(default="", max_length=2000)


def preserve_manual(automatic, current):
    manual = [c for c in current if c["kind"] == "manual"]
    result = copy.deepcopy(manual)
    for cut in merge_automatic(automatic):
        protected = [
            {
                "start": max(c["start"], cut["start"]) - cut["start"],
                "end": min(c["end"], cut["end"]) - cut["start"],
            }
            for c in manual
            if c["start"] < cut["end"] and c["end"] > cut["start"]
        ]
        for a, b in kept_ranges(cut["end"] - cut["start"], protected):
            result.append(
                dict(
                    cut,
                    id=story.identifier(),
                    start=cut["start"] + a,
                    end=cut["start"] + b,
                )
            )
    return result


def merge_automatic(cuts):
    result = []
    priority = {"silence": 0, "speech": 1, "filler": 2, "retake": 3}
    for cut in sorted(cuts, key=lambda c: c["start"]):
        if result and cut["start"] <= result[-1]["end"] + 0.001:
            previous = result[-1]
            previous["end"] = max(previous["end"], cut["end"])
            if priority.get(cut["kind"], 0) > priority.get(previous["kind"], 0):
                previous["kind"] = cut["kind"]
        else:
            result.append(copy.deepcopy(cut))
    return result


def prepare(editor, identifier, options):
    before = editor.repo.load(identifier)
    if before["subtitles"] and before.get("transcript"):
        # Human corrections are never silently replaced by the one-click workflow.
        generated = story.short_captions(
            before["transcript"].get("words", []),
            before["cuts"],
            before["media"]["duration"],
        )
        if before["subtitles"] != generated and before.get("captions_authored", True):
            raise ValueError(
                "This project already has captions. Use the explicit Generate action to replace them, or prepare a new clip."
            )
    editor.transcribe(identifier, options.language)
    p = editor.repo.load(identifier)
    words = p["transcript"].get("words", [])
    if not words:
        raise ValueError("Generate a word-timed transcript before preparing this cut.")
    duration = p["media"]["duration"]
    warnings = []
    try:
        quiet = media.detect_silence(
            editor.source(p), duration, -35, options.minimum_pause, options.padding
        )
    except ValueError as exc:
        if "whole recording" not in str(exc):
            raise
        quiet = []
        warnings.append(
            "The amplitude threshold marked the whole clip quiet; only recognized speech gaps were used."
        )
    regions = None
    if editor.vad_model.is_file():
        regions = media.speech_regions(
            editor.repo.directory(identifier) / "working" / "speech.wav",
            editor.vad_model, options.padding,
        )
        gaps = story.activity_gap_cuts(regions, duration, options.minimum_pause)
    else:
        gaps = story.speech_gap_cuts(
            p["transcript"].get("cues", []), duration, options.minimum_pause, options.padding,
        )
        warnings.append("Speech detection is not installed; pause cuts use amplitude and transcript gaps.")
    fillers = story.filler_cuts(words) if options.remove_fillers else []
    candidates = (
        story.retake_candidates(
            words, lambda a, b: media.audio_quality(editor.source(p), a, b)
        )
        if options.choose_retakes
        else []
    )

    def update(current):
        if current["subtitles"] != p["subtitles"]:
            raise ValueError(
                "Captions changed during preparation. Your corrections were preserved."
            )
        decisions = story.preserve_take_decisions(candidates, current["retakes"])
        max_words = (
            options.max_words
            if current["subtitle_style"]["max_words"]
            == before["subtitle_style"]["max_words"]
            else current["subtitle_style"]["max_words"]
        )
        current["subtitle_style"]["max_words"] = max_words
        cuts = preserve_manual(
            quiet + gaps + fillers + story.retake_cuts(decisions), current["cuts"]
        )
        current.update(
            cuts=cuts,
            retakes=decisions,
            subtitles=story.short_captions(words, cuts, duration, max_words),
            captions_authored=False,
            preparation=dict(options.model_dump(), max_words=max_words),
            preparation_warnings=warnings,
            analysis_cuts=merge_automatic(quiet + gaps + fillers),
            speech_regions=regions,
        )

    editor.repo.change(identifier, update)


def validate_production(editor, updates, duration):
    for name in ("overlays", "punches"):
        if name not in updates:
            continue
        validate_intervals(updates[name], duration)
        if len({o["id"] for o in updates[name]}) != len(updates[name]):
            raise ValueError("Each overlay and punch-in needs a unique ID.")
    for overlay in updates.get("overlays", []):
        asset = editor.library.get(overlay["asset_id"])
        if asset["kind"] not in {"image", "video", "audio"}:
            raise ValueError("Choose an image, video, or audio clip.")
        if overlay.get("audio") and not asset["has_audio"]:
            raise ValueError("This clip has no audio.")
        if (
            asset["kind"] in {"video", "audio"}
            and overlay["asset_in"] + overlay["end"] - overlay["start"]
            > asset["duration"] + 0.05
        ):
            raise ValueError(
                "The overlay extends beyond its video asset. Shorten its range or use a longer recording."
            )
    music = updates.get("music")
    if music:
        asset = editor.library.get(music["asset_id"])
        if not asset["has_audio"] or music["offset"] >= asset["duration"]:
            raise ValueError("Choose an audio asset and an offset inside its duration.")


def router(editor):
    api = APIRouter()
    downloads, download_lock = {}, threading.Lock()

    @api.get("/api/capture/config")
    def capture_config():
        path = editor.repo.root / "capture-settings.json"
        config = json.loads(path.read_text()) if path.exists() else {}
        return {
            "configured": bool(
                config.get("repo") and config.get("bundle") and config.get("scheme")
            ),
            "bundle": config.get("bundle"),
            "name": config.get("name", config.get("bundle")),
            "runs_on": "this Mac",
        }

    @api.post("/api/assets/capture-app")
    def capture_app(options: CaptureApp):
        settings_path = editor.repo.root / "capture-settings.json"
        if not settings_path.exists():
            raise ValueError(
                "Configure the app repository, scheme, bundle ID, and capture cache in .aiedit/capture-settings.json first."
            )
        config = json.loads(settings_path.read_text())
        job_id = uuid.uuid4().hex[:12]
        with download_lock:
            if any(j["status"] == "running" for j in downloads.values()):
                raise HTTPException(
                    409, "Wait for the current asset operation to finish."
                )
            downloads[job_id] = {
                "id": job_id,
                "status": "running",
                "message": "Capturing the app on this Mac…",
            }

        def execute():
            try:
                root = Path(config["cache_root"]).expanduser() / "Captures"
                root.mkdir(parents=True, exist_ok=True)
                output = root / (
                    job_id + (".png" if options.mode == "screenshot" else ".mp4")
                )
                script = (
                    Path(__file__).resolve().parent.parent / "scripts/capture_app.py"
                )
                command = [
                    sys.executable,
                    str(script),
                    "--settings",
                    str(settings_path),
                    "--mode",
                    options.mode,
                    "--seconds",
                    str(options.seconds),
                    "--output",
                    str(output),
                ]
                child = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = child.communicate(timeout=1200)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGINT)
                    try:
                        child.communicate(timeout=120)
                    except subprocess.TimeoutExpired:
                        raise ValueError(
                            "Capture timed out and native cleanup is still active. The Simulator reservation was retained; inspect the capture logs before retrying."
                        )
                    raise ValueError(
                        "Capture timed out. The owned native session was interrupted for cleanup."
                    )
                if child.returncode:
                    raise ValueError((stderr + "\n" + stdout)[-1600:])
                provenance = json.loads(
                    output.with_suffix(output.suffix + ".json").read_text()
                )
                asset = editor.library.import_file(
                    output,
                    name=config.get("name", "App") + " " + options.mode,
                    source_kind="simulator",
                    description=options.description
                    or "Local Simulator capture: " + config["bundle"],
                    tags=["app", "simulator"],
                    rights="User-owned app capture",
                )
                capture_file = editor.library.directory(asset["id"]) / "capture.json"
                capture_file.write_text(json.dumps(provenance, indent=2) + "\n")
                result = {"id": job_id, "status": "done", "asset": asset}
            except Exception as exc:
                result = {"id": job_id, "status": "error", "message": str(exc)[-1800:]}
            with download_lock:
                downloads[job_id] = result

        editor.pool.submit(execute)
        return downloads[job_id]

    @api.get("/api/assets")
    def assets(q: str = "", kind: str = ""):
        return editor.library.list(q, kind)

    @api.post("/api/assets/fetch")
    def fetch(options: FetchAsset):
        valid_url(options.url)
        job_id = uuid.uuid4().hex[:12]
        with download_lock:
            if any(j["status"] == "running" for j in downloads.values()):
                raise HTTPException(409, "Wait for the current download to finish.")
            downloads[job_id] = {"id": job_id, "status": "running"}

        def execute():
            try:
                asset = editor.library.fetch(
                    options.url, options.kind, options.tags, options.rights
                )
                result = {"id": job_id, "status": "done", "asset": asset}
            except Exception as exc:
                result = {"id": job_id, "status": "error", "message": str(exc)[-1500:]}
            with download_lock:
                downloads[job_id] = result

        editor.pool.submit(execute)
        return downloads[job_id]

    @api.get("/api/assets/jobs/{job_id}")
    def fetch_status(job_id: str):
        with download_lock:
            if job_id not in downloads:
                raise HTTPException(
                    404,
                    "Download job not found. It may have been interrupted when the editor restarted.",
                )
            return downloads[job_id]

    @api.post("/api/assets/import")
    def import_asset(options: AssetImport):
        data = options.model_dump()
        source = data.pop("path")
        return editor.library.import_file(source, **data)

    @api.post("/api/assets/upload")
    def upload(file: UploadFile):
        with tempfile.TemporaryDirectory(prefix="ai-editing-asset-") as folder:
            path = Path(folder) / "upload"
            import shutil

            with path.open("wb") as output:
                shutil.copyfileobj(file.file, output)
            return editor.library.import_file(
                path, filename=file.filename or "asset.png"
            )

    @api.put("/api/assets/{asset_id}")
    def metadata(asset_id: str, options: AssetMetadata):
        return editor.library.update(asset_id, **options.model_dump())

    @api.get("/api/assets/{asset_id}/media")
    def asset_file(asset_id: str):
        return FileResponse(editor.library.path(asset_id))

    @api.get("/api/assets/{asset_id}/waveform")
    def asset_waveform(asset_id: str):
        return FileResponse(editor.library.waveform(asset_id))

    @api.post("/api/projects/{identifier}/prepare")
    def prepare_project(identifier: str, options: PrepareOptions):
        p = editor.repo.load(identifier)
        if not p["media"]["has_audio"]:
            raise ValueError("This video has no speech track.")
        return editor.submit(
            identifier, "prepare", lambda i: prepare(editor, i, options)
        )

    @api.post("/api/projects/{identifier}/retakes/{retake_id}")
    def choose_take(identifier: str, retake_id: str, options: TakeDecision):
        with editor.repo.lock(identifier):
            p = editor.repo.load(identifier)
            candidate = next((c for c in p["retakes"] if c["id"] == retake_id), None)
            if not candidate:
                raise HTTPException(404, "Retake group not found.")

            def update(current):
                decision = next(c for c in current["retakes"] if c["id"] == retake_id)
                decision.update(
                    selected=options.selected,
                    reason=options.reason,
                    status="selected" if options.selected is not None else "keep_both",
                    automatic=False,
                )
                automatic = current.get(
                    "analysis_cuts",
                    [
                        c
                        for c in current["cuts"]
                        if c["kind"] not in {"manual", "retake"}
                    ],
                )
                current["cuts"] = preserve_manual(
                    automatic + story.retake_cuts(current["retakes"]), current["cuts"]
                )
                if not current.get("captions_authored", True) and current.get(
                    "transcript", {}
                ).get("words"):
                    current["subtitles"] = story.short_captions(
                        current["transcript"]["words"],
                        current["cuts"],
                        current["media"]["duration"],
                        current["subtitle_style"]["max_words"],
                    )

            return editor.repo.change(identifier, update)

    @api.get("/api/hooks")
    def hooks(topic: str = ""):
        return editor.hooks.suggest(topic)

    @api.post("/api/hooks")
    def add_hook(options: HookEntry):
        valid_url(options.source_url)
        return editor.hooks.add(options.model_dump())

    return api
