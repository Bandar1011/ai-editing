"""Minimal production models, preparation jobs, asset and story API."""

import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import story
from .analysis import CONTRACTS, key_for
from .assets import valid_url
from .presets import CAPTIONS, REFERENCE_SOUND, SPEECH
from .timeline import kept_ranges, validate_intervals


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EntranceSound(Strict):
    asset_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    asset_in: float = Field(default=0, ge=0)
    volume: float = Field(default=REFERENCE_SOUND["volume"], ge=0, le=1)
    enabled: bool = True


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
    role: Literal["reference", "title", "graphic"] | None = None
    entrance_sound: EntranceSound | None = None


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
    minimum_pause: float = Field(default=SPEECH["minimum_pause"], ge=0.06, le=5)
    padding: float = Field(default=SPEECH["padding"], ge=0.01, le=0.6)
    choose_retakes: bool = True
    max_words: int = Field(default=CAPTIONS["max_words"], ge=1, le=3)
    remove_fillers: bool = True


class TakeDecision(Strict):
    base_revision: int | None = Field(default=None, ge=1)
    selected: int | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)


class CaptionFix(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    text: str = Field(min_length=1, max_length=5000)


class TakeChoice(TakeDecision):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")


class EditorialChanges(Strict):
    base_revision: int = Field(ge=1)
    caption_fixes: list[CaptionFix] = Field(default_factory=list, max_length=1000)
    take_choices: list[TakeChoice] = Field(default_factory=list, max_length=200)
    overlays: list[Overlay] = Field(default_factory=list, max_length=100)
    story: StoryPlan | None = None


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
    if (
        before["subtitles"]
        and before.get("captions_authored", True)
        and not before.get("preparation_key")
    ):
        raise ValueError(
            "This project already has captions. Use the explicit Generate action to replace them, or prepare a new clip."
        )
    analysis = editor.analysis(identifier)
    if (
        before.get("preparation_key")
        and before.get("captions_authored", False)
        and before.get("preparation") == options.model_dump()
        and (
            options.language == "auto"
            or before.get("transcript", {}).get("language") == options.language
        )
    ):
        editor.progress(identifier, stage="apply", status="done", reused=True)
        return
    if not before["media"]["has_audio"] or analysis.silent():
        signature = key_for(
            {
                "source": analysis.source_key,
                "visual_only": True,
                "signal": analysis.keys.get("signal"),
            }
        )

        def preserve(current):
            current.update(
                preparation_key=signature,
                preparation_kind="visual",
                preparation_warnings=[
                    "No speech signal. Existing footage, cuts and captions were preserved."
                ],
            )

        with editor.repo.lock(identifier):
            if editor.repo.load(identifier).get("preparation_key") != signature:
                editor.repo.change(identifier, preserve)
        return
    transcript = editor.read_transcript(identifier, options.language, analysis=analysis)
    words = transcript.get("words", [])
    if not words:
        raise ValueError("Generate a word-timed transcript before preparing this cut.")
    duration = before["media"]["duration"]
    warnings = []
    quiet_result = analysis.quiet(
        duration, SPEECH["threshold_db"], options.minimum_pause, options.padding
    )
    quiet = quiet_result["cuts"]
    if quiet_result["whole_recording_quiet"]:
        warnings.append(
            "The amplitude threshold marked the whole clip quiet; only recognized speech gaps were used."
        )
    regions = None
    if editor.vad_model.is_file():
        regions = analysis.regions(editor.vad_model, options.padding)
        gaps = story.activity_gap_cuts(regions, duration, options.minimum_pause)
    else:
        gaps = story.speech_gap_cuts(
            transcript.get("cues", []), duration, options.minimum_pause, options.padding
        )
        warnings.append(
            "Speech detection is not installed; pause cuts use amplitude and transcript gaps."
        )
    fillers = story.filler_cuts(words) if options.remove_fillers else []
    candidates = analysis.retakes(words) if options.choose_retakes else []
    signature = key_for(
        {
            "schema": CONTRACTS["prepare"],
            "source": analysis.source_key,
            "transcript": transcript,
            "analysis": analysis.keys,
            "options": options.model_dump(),
            "vad": editor.vad_model.is_file(),
        }
    )
    editor.progress(identifier, stage="apply", status="running")
    with editor.repo.lock(identifier):
        current = editor.repo.load(identifier)
        # An identical completed request must not regroup approved text or reset edits.
        if current.get("preparation_key") == signature:
            return
        if current["subtitles"] != before["subtitles"]:
            raise ValueError(
                "Captions changed during preparation. Your corrections were preserved."
            )
        if current["subtitles"] and current.get("captions_authored", True):
            raise ValueError(
                "This project already has captions. Use the explicit Generate action to replace them, or prepare a new clip."
            )

        def update(current):
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
                transcript=transcript,
                captions_authored=False,
                preparation=dict(options.model_dump(), max_words=max_words),
                preparation_key=signature,
                preparation_kind="speech",
                preparation_warnings=warnings,
                analysis_cuts=merge_automatic(quiet + gaps + fillers),
                speech_regions=regions,
            )

        editor.repo.change(identifier, update)


def normalize_overlays(current, submitted, library):
    previous = {o["id"]: o for o in current}
    result = []
    for overlay in submitted:
        value = overlay.model_dump()
        before = previous.get(overlay.id, {})
        for field in ("role", "entrance_sound"):
            if field not in overlay.model_fields_set:
                if field in before:
                    value[field] = copy.deepcopy(before[field])
                else:
                    value.pop(field, None)
        if (
            overlay.id not in previous
            and value.get("role") == "reference"
            and "entrance_sound" not in overlay.model_fields_set
        ):
            value["entrance_sound"] = library.reference_sound_default(required=True)
        result.append(value)
    return result


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
        if overlay.get("role") and asset["kind"] not in {"image", "video"}:
            raise ValueError(
                "Only images and videos can be visual references, titles, or graphics."
            )
        if overlay.get("entrance_sound"):
            if overlay.get("role") != "reference":
                raise ValueError(
                    "Only screenshot/B-roll references can have a pop sound."
                )
            editor.library.validate_reference_sound(overlay["entrance_sound"])
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


def apply_take(current, retake_id, options):
    duration = current["media"]["duration"]
    previously_visible = kept_ranges(duration, current["cuts"])
    decision = next((c for c in current["retakes"] if c["id"] == retake_id), None)
    if decision is None:
        raise ValueError("Retake group not found. Read the latest context.")
    decision.update(
        selected=options.selected,
        reason=options.reason,
        status="selected" if options.selected is not None else "keep_both",
        automatic=False,
    )
    automatic = current.get(
        "analysis_cuts",
        [c for c in current["cuts"] if c["kind"] not in {"manual", "retake"}],
    )
    current["cuts"] = preserve_manual(
        automatic + story.retake_cuts(current["retakes"]), current["cuts"]
    )
    if not current.get("captions_authored", True) and current.get("transcript", {}).get(
        "words"
    ):
        current["subtitles"] = story.short_captions(
            current["transcript"]["words"],
            current["cuts"],
            current["media"]["duration"],
            current["subtitle_style"]["max_words"],
        )
    elif current.get("transcript", {}).get("words"):
        visible = kept_ranges(duration, current["cuts"])
        existing = current["subtitles"]
        missing = []
        for word in current["transcript"]["words"]:
            centre = (word["start"] + word["end"]) / 2
            if (
                any(a <= centre < b for a, b in visible)
                and not any(a <= centre < b for a, b in previously_visible)
                and not any(
                    c["start"] < word["end"] and c["end"] > word["start"]
                    for c in existing
                )
            ):
                missing.append(word)
        exclusions = current["cuts"] + [
            dict(start=c["start"], end=c["end"], enabled=True) for c in existing
        ]
        additions = story.short_captions(
            missing, exclusions, duration, current["subtitle_style"]["max_words"]
        )
        current["subtitles"] = sorted(
            existing + additions, key=lambda cue: cue["start"]
        )


def apply_editorial(editor, identifier, options, *, receipt=None):
    with editor.repo.lock(identifier):
        p = editor.repo.load(identifier)
        if options.base_revision != p["revision"]:
            raise HTTPException(
                409,
                "The project changed. Read the latest context before applying decisions.",
            )
        if options.take_choices and (options.caption_fixes or options.overlays):
            raise ValueError(
                "Choose takes first, then read updated context before fixing captions or placing visuals."
            )
        for items in (
            options.caption_fixes,
            options.take_choices,
            options.overlays,
        ):
            if len({item.id for item in items}) != len(items):
                raise ValueError("Send each decision ID only once.")

        def update(current):
            previous_caption_ids = {c["id"] for c in current["subtitles"]}
            for correction in options.caption_fixes:
                if not correction.text.strip():
                    raise ValueError("A subtitle correction must contain text.")
                cue = next(
                    (c for c in current["subtitles"] if c["id"] == correction.id),
                    None,
                )
                if cue is None:
                    raise ValueError("Caption not found. Read the latest context.")
                if cue["text"] != correction.text:
                    cue["text"] = correction.text
                    current["captions_authored"] = True
            if options.caption_fixes:
                story.split_existing_captions(current["subtitles"])
            for choice in options.take_choices:
                if choice.base_revision not in (None, options.base_revision):
                    raise ValueError("Use the same revision for every take choice.")
                apply_take(current, choice.id, choice)
            if options.overlays:
                remaining = {o.id: o for o in options.overlays}
                combined = []
                for previous in current["overlays"]:
                    submitted = remaining.pop(previous["id"], None)
                    value = (
                        dict(previous, **submitted.model_dump(exclude_unset=True))
                        if submitted is not None
                        else previous
                    )
                    combined.append(Overlay.model_validate(value))
                combined += list(remaining.values())
                if len(combined) > 100:
                    raise ValueError("Use at most 100 overlays.")
                overlays = normalize_overlays(
                    current["overlays"], combined, editor.library
                )
                validate_production(
                    editor, {"overlays": overlays}, current["media"]["duration"]
                )
                current["overlays"] = overlays
            if options.story is not None:
                current["story"].update(
                    options.story.model_dump(exclude_unset=True)
                )

            if receipt is not None:
                job = current["jobs"].get("assistant", {})
                if job.get("id") != receipt["run_id"]:
                    raise ValueError("The AI editing session changed.")
                job["receipts"].append(dict(receipt, revision=current["revision"] + 1))
                if options.take_choices:
                    generated = current.get("assistant_caption_baseline", {}).get("generated", {}).copy()
                    generated.update({
                        c["id"]: key_for(c) for c in current["subtitles"]
                        if not current.get("captions_authored", True) or c["id"] not in previous_caption_ids
                    })
                    current["assistant_caption_baseline"] = {
                        "preparation_key": current["preparation_key"],
                        "generated": generated,
                    }

        return editor.repo.change(identifier, update)


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
            if any(j["status"] in {"queued", "running"} for j in downloads.values()):
                raise HTTPException(
                    409, "Wait for the current asset operation to finish."
                )
            downloads[job_id] = {
                "id": job_id,
                "status": "queued",
                "queued_at": time.time(),
                "message": "Waiting for the media worker",
            }

        def execute():
            with download_lock:
                downloads[job_id].update(
                    status="running",
                    started_at=time.time(),
                    message="Capturing the app on this Mac",
                )
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
                downloads[job_id].update(result, finished_at=time.time())

        editor.pool.submit(execute)
        return downloads[job_id]

    @api.get("/api/assets")
    def assets(q: str = "", kind: str = ""):
        return editor.library.list(q, kind)

    @api.get("/api/assets/reference-sound")
    def reference_sound():
        return editor.library.reference_sound_default()

    @api.post("/api/assets/fetch")
    def fetch(options: FetchAsset):
        valid_url(options.url)
        job_id = uuid.uuid4().hex[:12]
        with download_lock:
            if any(j["status"] in {"queued", "running"} for j in downloads.values()):
                raise HTTPException(409, "Wait for the current download to finish.")
            downloads[job_id] = {
                "id": job_id,
                "status": "queued",
                "queued_at": time.time(),
                "message": "Waiting for the media worker",
            }

        def execute():
            with download_lock:
                downloads[job_id].update(
                    status="running",
                    started_at=time.time(),
                    message="Downloading to your local library",
                )
            try:
                asset = editor.library.fetch(
                    options.url, options.kind, options.tags, options.rights
                )
                result = {"id": job_id, "status": "done", "asset": asset}
            except Exception as exc:
                result = {"id": job_id, "status": "error", "message": str(exc)[-1500:]}
            with download_lock:
                downloads[job_id].update(result, finished_at=time.time())

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
    def prepare_project(identifier: str, options: PrepareOptions, request: Request):
        p = editor.repo.load(identifier)

        def run(identifier):
            if not editor.repo.load(identifier)["media_ready"]:
                editor.progress(identifier, stage="preview", status="running")
                editor.preview(identifier)
            prepare(editor, identifier, options)

        return editor.submit(
            identifier,
            "prepare",
            run,
            after_preview=True,
            request_key=key_for(options.model_dump()),
            after_success=(
                lambda identifier: editor.assistant.start(
                    identifier,
                    str(request.base_url) + f"api/projects/{identifier}/assistant/tools",
                )
            ) if editor.assistant is not None else None,
        )

    @api.post("/api/projects/{identifier}/retakes/{retake_id}")
    def choose_take(identifier: str, retake_id: str, options: TakeDecision):
        with editor.repo.lock(identifier):
            p = editor.repo.load(identifier)
            if (
                options.base_revision is not None
                and options.base_revision != p["revision"]
            ):
                raise HTTPException(
                    409,
                    "The project changed. Read the latest take choices before saving.",
                )
            candidate = next((c for c in p["retakes"] if c["id"] == retake_id), None)
            if not candidate:
                raise HTTPException(404, "Retake group not found.")

            def update(current):
                apply_take(current, retake_id, options)

            return editor.repo.change(identifier, update)

    @api.patch("/api/projects/{identifier}/editorial")
    def editorial_changes(identifier: str, options: EditorialChanges):
        return apply_editorial(editor, identifier, options)

    @api.get("/api/hooks")
    def hooks(topic: str = ""):
        return editor.hooks.suggest(topic)

    @api.post("/api/hooks")
    def add_hook(options: HookEntry):
        valid_url(options.source_url)
        return editor.hooks.add(options.model_dump())

    return api
