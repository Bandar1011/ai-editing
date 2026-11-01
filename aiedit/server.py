"""Loopback-only editor API and static web application."""

import copy
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import media, production, story
from .assets import AssetLibrary
from .hooks import HookLibrary
from .timeline import (
    kept_ranges,
    parse_srt,
    remap_subtitles,
    srt_text,
    validate_intervals,
)

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".mts",
    ".m2ts",
    ".mpeg",
    ".mpg",
}


class Cut(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    start: float
    end: float
    enabled: bool = True
    kind: Literal["silence", "manual", "retake", "speech", "filler"] = "manual"


class Subtitle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    start: float
    end: float
    text: str = Field(max_length=5000)


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    font_size: int = Field(default=48, ge=24, le=80)
    position: Literal["top", "bottom"] = "bottom"
    enabled: bool = True
    uppercase: bool = True
    outline: float = Field(default=4, ge=0, le=8)
    margin_percent: float = Field(default=18, ge=5, le=35)
    max_words: int = Field(default=3, ge=1, le=3)


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(default="", max_length=4000)
    target: str = Field(default="", max_length=200)
    rights: str = Field(default="", max_length=4000)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=2000)
    purpose: str = Field(default="", max_length=2000)


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int
    name: str = Field(min_length=1, max_length=200)
    cuts: list[Cut] = Field(max_length=5000)
    subtitles: list[Subtitle] = Field(max_length=10000)
    subtitle_style: SubtitleStyle
    brief: Brief
    references: list[Reference] = Field(max_length=200)
    overlays: list[production.Overlay] | None = Field(default=None, max_length=100)
    punches: list[production.Punch] | None = Field(default=None, max_length=30)
    music: production.Music | None = None
    story: production.StoryPlan | None = None
    split_points: list[float] | None = Field(default=None, max_length=5000)


class SilenceOptions(BaseModel):
    threshold_db: float = Field(default=-35, ge=-65, le=-10, allow_inf_nan=False)
    minimum: float = Field(default=0.55, ge=0.15, le=5, allow_inf_nan=False)
    padding: float = Field(default=0.12, ge=0, le=0.6, allow_inf_nan=False)


class TranscribeOptions(BaseModel):
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")


class ExportOptions(BaseModel):
    burn_subtitles: bool = True
    label: str = Field(default="", max_length=120)
    plain: bool = False
    format: Literal["source", "vertical"] = "source"


class ReviewNote(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    export_file: str
    time: float = Field(ge=0)
    change: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    scope: Literal["this_edit", "reusable"] = "this_edit"


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolved_in: str | None = None


class ImportOptions(BaseModel):
    path: str


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.projects = self.root / "projects"
        self.projects.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def directory(self, identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", identifier):
            raise HTTPException(404, "Project not found.")
        return self.projects / identifier

    def lock(self, identifier: str):
        with self._guard:
            return self._locks.setdefault(identifier, threading.RLock())

    def load(self, identifier: str) -> dict:
        with self.lock(identifier):
            try:
                project = json.loads(
                    (self.directory(identifier) / "project.json").read_text()
                )
                for key, value in {
                    "split_points": [],
                    "overlays": [],
                    "punches": [],
                    "music": None,
                    "retakes": [],
                    "story": production.StoryPlan().model_dump(),
                }.items():
                    project.setdefault(key, value)
                project["subtitle_style"] = dict(
                    SubtitleStyle().model_dump(), **project["subtitle_style"]
                )
                for overlay in project["overlays"]:
                    overlay.setdefault("audio", False)
                    overlay.setdefault("volume", 0.4)
                return project
            except FileNotFoundError:
                raise HTTPException(404, "Project not found.")

    def write(self, project: dict) -> dict:
        identifier = project["id"]
        with self.lock(identifier):
            project["updated_at"] = time.time()
            target = self.directory(identifier) / "project.json"
            if target.is_file():
                history = target.parent / "history"
                history.mkdir(exist_ok=True)
                previous = json.loads(target.read_text())
                backup = history / f"revision-{previous['revision']:06}.json"
                if not backup.exists():
                    shutil.copyfile(target, backup)
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
            temp.replace(target)
            return copy.deepcopy(project)

    def change(self, identifier: str, mutate) -> dict:
        with self.lock(identifier):
            project = self.load(identifier)
            mutate(project)
            project["revision"] += 1
            return self.write(project)

    def list(self) -> list[dict]:
        result = []
        for path in self.projects.glob("*/project.json"):
            try:
                p = json.loads(path.read_text())
                result.append({k: p[k] for k in ("id", "name", "media", "updated_at")})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda p: p["updated_at"], reverse=True)


class Editor:
    def __init__(self, directory: Path):
        self.repo = Repository(directory)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-editing")
        self.library = AssetLibrary(directory / "library" / "assets")
        self.hooks = HookLibrary(directory / "library")
        self.model = Path(
            os.environ.get("AIEDIT_MODEL", directory / "models" / "ggml-base.bin")
        )
        self.active: set[str] = set()
        self.job_lock = threading.Lock()

    def create(self, source: Path, filename: str) -> dict:
        extension = Path(filename).suffix.lower()
        if extension not in EXTENSIONS:
            raise ValueError(
                "Choose an MP4, MOV, WebM, or another supported video file."
            )
        info = media.probe(source)
        identifier = uuid.uuid4().hex[:12]
        folder = self.repo.directory(identifier)
        folder.mkdir()
        for name in ("source", "working", "references", "exports"):
            (folder / name).mkdir()
        target = folder / "source" / ("original" + extension)
        shutil.copyfile(source, target)
        with target.open("rb") as handle:
            source_checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        project = {
            "id": identifier,
            "name": Path(filename).stem[:200] or "Untitled video",
            "filename": Path(filename).name,
            "source_file": target.relative_to(folder).as_posix(),
            "revision": 1,
            "media": info,
            "media_ready": False,
            "waveform_ready": False,
            "cuts": [],
            "subtitles": [],
            "subtitle_style": SubtitleStyle().model_dump(),
            "silence_options": SilenceOptions().model_dump(),
            "jobs": {},
            "exports": [],
            "brief": Brief().model_dump(),
            "references": [],
            "reviews": [],
            "source_sha256": source_checksum,
        }
        self.repo.write(project)
        self.submit(identifier, "preview", self.preview)
        return self.repo.load(identifier)

    def submit(self, identifier: str, kind: str, worker, *args) -> dict:
        with self.job_lock:
            if identifier in self.active:
                raise HTTPException(409, "Wait for the current operation to finish.")
            self.active.add(identifier)
        self.repo.change(
            identifier,
            lambda p: p["jobs"].update(
                {
                    kind: {
                        "status": "running",
                        "message": "Working…",
                        "started_at": time.time(),
                    }
                }
            ),
        )

        def execute():
            try:
                worker(identifier, *args)
                self.repo.change(
                    identifier,
                    lambda p: p["jobs"][kind].update(
                        status="done", message="Complete", finished_at=time.time()
                    ),
                )
            except Exception as exc:
                message = str(exc.detail if isinstance(exc, HTTPException) else exc)
                self.repo.change(
                    identifier,
                    lambda p: p["jobs"][kind].update(
                        status="error", message=message[-1800:], finished_at=time.time()
                    ),
                )
            finally:
                with self.job_lock:
                    self.active.discard(identifier)

        self.pool.submit(execute)
        return self.repo.load(identifier)

    def source(self, project: dict) -> Path:
        return self.repo.directory(project["id"]) / project["source_file"]

    def preview(self, identifier: str):
        p = self.repo.load(identifier)
        folder = self.repo.directory(identifier) / "working"
        media.make_proxy(self.source(p), folder, p["media"]["has_audio"])
        self.repo.change(
            identifier,
            lambda p: p.update(
                media_ready=True, waveform_ready=(folder / "waveform.png").is_file()
            ),
        )

    def silence(self, identifier: str, options: SilenceOptions):
        p = self.repo.load(identifier)
        cuts = media.detect_silence(
            self.source(p),
            p["media"]["duration"],
            options.threshold_db,
            options.minimum,
            options.padding,
        )

        def update(project):
            project["analysis_cuts"] = production.merge_automatic(cuts)
            project["cuts"] = production.preserve_manual(
                cuts + story.retake_cuts(project["retakes"]), project["cuts"]
            )
            project["silence_options"] = options.model_dump()

        self.repo.change(identifier, update)

    def transcribe(self, identifier: str, language: str):
        p = self.repo.load(identifier)
        working = self.repo.directory(identifier) / "working"
        cues = media.transcribe(self.source(p), working, self.model, language)
        duration = p["media"]["duration"]
        cues = [
            dict(
                c, start=max(0, min(duration, c["start"])), end=min(duration, c["end"])
            )
            for c in cues
            if min(duration, c["end"]) - c["start"] >= 0.02
        ]
        transcript = {
            "language": language,
            "source_file": p["filename"],
            "created_at": time.time(),
            "cues": cues,
        }
        word_file = working / "word-transcript.json"
        if word_file.is_file():
            transcript.update(json.loads(word_file.read_text()))
            cues = story.short_captions(
                transcript["words"], max_words=p["subtitle_style"]["max_words"]
            )
        (working / "transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"
        )

        def update(project):
            if project["subtitles"] != p["subtitles"]:
                raise ValueError(
                    "Captions changed during transcription. Your edits were preserved; the new transcript is saved in working/transcript.json."
                )
            project.update(
                subtitles=(
                    story.short_captions(
                        transcript["words"],
                        max_words=project["subtitle_style"]["max_words"],
                    )
                    if transcript.get("words")
                    else cues
                ),
                transcript=transcript,
                captions_authored=False,
            )

        self.repo.change(identifier, update)

    def export(
        self,
        identifier: str,
        snapshot: dict,
        burn_subtitles: bool,
        label: str = "",
        plain: bool = False,
        resolved_assets=None,
        format="source",
    ):
        resolved_assets = (
            resolved_assets
            if resolved_assets is not None
            else (self.library.resolve(snapshot) if not plain else {})
        )
        output = media.export_video(
            snapshot,
            self.source(snapshot),
            self.repo.directory(identifier) / "exports",
            burn_subtitles and snapshot["subtitle_style"]["enabled"],
            resolved_assets,
            plain,
            format,
        )
        kept = kept_ranges(snapshot["media"]["duration"], snapshot["cuts"])
        version = len(snapshot["exports"]) + 1
        captioned = (
            burn_subtitles
            and not plain
            and snapshot["subtitle_style"]["enabled"]
            and bool(snapshot["subtitles"])
        )
        with output.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        encoded = media.probe(output)
        result = {
            "file": output.name,
            "created_at": time.time(),
            "revision": snapshot["revision"],
            "version": version,
            "label": label.strip()
            or f"{'Captioned' if captioned else 'Plain'} cut {version:03}",
            "captioned": captioned,
            "duration": encoded["duration"],
            "story_duration": sum(b - a for a, b in kept),
            "encoded_media": encoded,
            "edit_state": {
                key: snapshot[key]
                for key in (
                    "cuts",
                    "subtitles",
                    "subtitle_style",
                    "overlays",
                    "punches",
                    "music",
                    "story",
                    "split_points",
                )
            },
            "source_ranges": [{"start": a, "end": b} for a, b in kept],
            "brief": snapshot["brief"],
            "references": snapshot["references"],
            "source_filename": snapshot["filename"],
            "media": snapshot["media"],
            "source_sha256": snapshot.get("source_sha256"),
            "sha256": checksum,
            "captions_file": output.with_suffix(".srt").name,
            "manifest_file": output.with_suffix(".json").name,
            "render_settings": {
                "plain": plain,
                "burn_subtitles": captioned,
                "format": format,
            },
            "assets": (
                [item["metadata"] for item in resolved_assets.values()]
                if not plain
                else []
            ),
            "retakes": snapshot.get("retakes", []),
        }
        output.with_suffix(".srt").write_text(
            srt_text(remap_subtitles(snapshot["subtitles"], kept)), encoding="utf-8"
        )
        output.with_suffix(".json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        self.repo.change(identifier, lambda p: p["exports"].append(result))


def create_app(data_dir: Path | None = None) -> FastAPI:
    editor = Editor(data_dir or Path(os.environ.get("AIEDIT_DATA", ROOT / ".aiedit")))

    @asynccontextmanager
    async def lifespan(app):
        # A killed render must not leave the UI showing an eternal running job.
        for summary in editor.repo.list():
            p = editor.repo.load(summary["id"])
            if any(j["status"] == "running" for j in p["jobs"].values()):

                def interrupted(project):
                    for job in project["jobs"].values():
                        if job["status"] == "running":
                            job.update(
                                status="error",
                                message="Interrupted when the editor stopped. Run the operation again.",
                            )

                editor.repo.change(p["id"], interrupted)
        yield
        editor.pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="AI Editing", lifespan=lifespan)
    app.state.editor = editor
    app.include_router(production.router(editor))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def loopback_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            port = request.url.port or 80
            if origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                return JSONResponse(
                    {"detail": "Open the editor on this computer to make changes."},
                    status_code=403,
                )
        response = await call_next(request)
        if request.url.path.startswith(("/api/", "/static/")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/health")
    def health():
        return {
            "status": "ready",
            "transcription_ready": editor.model.is_file(),
            "whisper_ready": bool(shutil.which("whisper-cli")),
            "ffmpeg": media.binary("ffmpeg"),
        }

    @app.get("/api/projects")
    def projects():
        return editor.repo.list()

    @app.get("/api/history")
    def edit_history(q: str = "", reusable: bool = False):
        matches = []
        terms = q.casefold().split()
        for summary in editor.repo.list():
            p = editor.repo.load(summary["id"])
            for note in p["reviews"]:
                if reusable and note["scope"] != "reusable":
                    continue
                text = f"{p['name']} {note['change']} {note['reason']}".casefold()
                if all(term in text for term in terms):
                    matches.append(
                        dict(note, project_id=p["id"], project_name=p["name"])
                    )
        return sorted(matches, key=lambda n: n["created_at"], reverse=True)

    @app.post("/api/projects/import")
    def import_path(options: ImportOptions):
        path = Path(options.path).expanduser().resolve()
        if not path.is_file():
            raise HTTPException(400, "That video file does not exist on this computer.")
        return editor.create(path, path.name)

    @app.post("/api/projects/upload")
    def upload_video(file: UploadFile):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ai-editing-upload-") as folder:
            target = Path(folder) / "upload"
            with target.open("wb") as output:
                shutil.copyfileobj(file.file, output, length=1024 * 1024)
            return editor.create(target, file.filename or "video.mp4")

    @app.get("/api/projects/{identifier}")
    def project(identifier: str):
        return editor.repo.load(identifier)

    @app.put("/api/projects/{identifier}")
    def save_project(identifier: str, edit: Edit):
        with editor.repo.lock(identifier):
            p = editor.repo.load(identifier)
            if edit.base_revision != p["revision"]:
                raise HTTPException(
                    409, "This project changed elsewhere. Refresh before saving."
                )
            updates = edit.model_dump(exclude={"base_revision"}, exclude_unset=True)
            if edit.split_points is not None:
                if any(
                    not math.isfinite(t) or not 0 < t < p["media"]["duration"]
                    for t in edit.split_points
                ):
                    raise ValueError("Split points must stay inside the source video.")
                updates["split_points"] = sorted(set(edit.split_points))
            else:
                updates.pop("split_points", None)
            if edit.overlays is not None:
                updates["overlays"] = [
                    overlay.model_dump() for overlay in edit.overlays
                ]
            for key in ("cuts", "subtitles"):
                validate_intervals(updates[key], p["media"]["duration"])
                if len({c["id"] for c in updates[key]}) != len(updates[key]):
                    raise ValueError("Each cut and subtitle needs its own unique ID.")
            if updates["subtitles"] != p["subtitles"]:
                story.split_existing_captions(updates["subtitles"])
            production.validate_production(editor, updates, p["media"]["duration"])
            if updates["subtitles"] != p["subtitles"]:
                updates["captions_authored"] = True
            for reference in updates["references"]:
                if reference["url"] and (
                    urlparse(reference["url"]).scheme not in {"https", "http"}
                    or not urlparse(reference["url"]).netloc
                ):
                    raise ValueError(
                        "Reference links must be complete http or https URLs."
                    )
            return editor.repo.change(identifier, lambda p: p.update(updates))

    @app.get("/api/projects/{identifier}/media")
    def video(identifier: str):
        editor.repo.load(identifier)
        path = editor.repo.directory(identifier) / "working" / "preview.mp4"
        if not path.is_file():
            raise HTTPException(404, "The video preview is still being prepared.")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/projects/{identifier}/waveform")
    def waveform(identifier: str):
        editor.repo.load(identifier)
        path = editor.repo.directory(identifier) / "working" / "waveform.png"
        if not path.is_file():
            raise HTTPException(404, "No waveform available.")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/projects/{identifier}/silence")
    def silence(identifier: str, options: SilenceOptions):
        p = editor.repo.load(identifier)
        if not p["media"]["has_audio"]:
            raise HTTPException(400, "This video has no audio track.")
        return editor.submit(identifier, "silence", editor.silence, options)

    @app.post("/api/projects/{identifier}/transcribe")
    def transcribe(identifier: str, options: TranscribeOptions):
        p = editor.repo.load(identifier)
        if not p["media"]["has_audio"]:
            raise HTTPException(400, "This video has no audio track.")
        if not editor.model.is_file():
            raise HTTPException(
                409,
                "Install the local speech model first: uv run python scripts/setup_model.py",
            )
        return editor.submit(
            identifier, "transcribe", editor.transcribe, options.language
        )

    @app.get("/api/projects/{identifier}/transcript.json")
    def transcript(identifier: str):
        p = editor.repo.load(identifier)
        if "transcript" not in p:
            raise HTTPException(404, "Generate a transcript first.")
        return JSONResponse(
            p["transcript"],
            headers={
                "Content-Disposition": 'attachment; filename="source-transcript.json"'
            },
        )

    @app.get("/api/projects/{identifier}/transcript.srt")
    def source_captions(identifier: str):
        p = editor.repo.load(identifier)
        if "transcript" not in p:
            raise HTTPException(404, "Generate a transcript first.")
        return Response(
            srt_text(p["transcript"]["cues"]),
            media_type="application/x-subrip",
            headers={
                "Content-Disposition": 'attachment; filename="source-transcript.srt"'
            },
        )

    @app.post("/api/projects/{identifier}/subtitles/import")
    def import_subtitles(identifier: str, file: UploadFile):
        p = editor.repo.load(identifier)
        content = file.file.read(10_000_001)
        if len(content) > 10_000_000:
            raise HTTPException(400, "The subtitle file is too large.")
        cues = parse_srt(content.decode("utf-8-sig"))
        if not cues:
            raise ValueError("No captions were found. Choose a UTF-8 SRT file.")
        validate_intervals(cues, p["media"]["duration"])
        story.split_existing_captions(cues)
        return editor.repo.change(
            identifier, lambda p: p.update(subtitles=cues, captions_authored=True)
        )

    @app.get("/api/projects/{identifier}/subtitles.srt")
    def subtitles(identifier: str):
        p = editor.repo.load(identifier)
        cues = remap_subtitles(
            p["subtitles"], kept_ranges(p["media"]["duration"], p["cuts"])
        )
        return Response(
            srt_text(cues),
            media_type="application/x-subrip",
            headers={"Content-Disposition": 'attachment; filename="subtitles.srt"'},
        )

    @app.post("/api/projects/{identifier}/export")
    def export(identifier: str, options: ExportOptions):
        p = editor.repo.load(identifier)
        return editor.submit(
            identifier,
            "export",
            editor.export,
            p,
            options.burn_subtitles,
            options.label,
            options.plain,
            editor.library.resolve(p) if not options.plain else {},
            options.format,
        )

    @app.get("/api/projects/{identifier}/exports/{filename}")
    def download(identifier: str, filename: str):
        p = editor.repo.load(identifier)
        allowed = {
            e[key]
            for e in p["exports"]
            for key in ("file", "captions_file", "manifest_file")
        }
        if filename not in allowed:
            raise HTTPException(404, "Export not found.")
        path = editor.repo.directory(identifier) / "exports" / filename
        mime = {
            ".mp4": "video/mp4",
            ".srt": "application/x-subrip",
            ".json": "application/json",
        }[path.suffix]
        return FileResponse(path, media_type=mime, filename=filename)

    @app.post("/api/projects/{identifier}/reviews")
    def add_review(identifier: str, note: ReviewNote):
        with editor.repo.lock(identifier):
            p = editor.repo.load(identifier)
            exported = next(
                (e for e in p["exports"] if e["file"] == note.export_file), None
            )
            if not exported:
                raise HTTPException(404, "Choose an existing export to review.")
            if note.time > exported["duration"]:
                raise ValueError("Review time must be inside the selected export.")
            if not note.change.strip() or not note.reason.strip():
                raise ValueError("Describe the change and why it matters.")
            value = dict(
                note.model_dump(),
                id=uuid.uuid4().hex[:12],
                created_at=time.time(),
                resolved_in=None,
            )
            return editor.repo.change(identifier, lambda p: p["reviews"].append(value))

    @app.patch("/api/projects/{identifier}/reviews/{note_id}")
    def resolve_review(identifier: str, note_id: str, resolution: Resolution):
        with editor.repo.lock(identifier):
            p = editor.repo.load(identifier)
            note = next((n for n in p["reviews"] if n["id"] == note_id), None)
            if not note:
                raise HTTPException(404, "Review note not found.")
            if resolution.resolved_in:
                original = next(
                    e for e in p["exports"] if e["file"] == note["export_file"]
                )
                fixed = next(
                    (e for e in p["exports"] if e["file"] == resolution.resolved_in),
                    None,
                )
                if not fixed or fixed["version"] <= original["version"]:
                    raise ValueError(
                        "Choose a later export that demonstrates the correction."
                    )

            def update(project):
                next(n for n in project["reviews"] if n["id"] == note_id)[
                    "resolved_in"
                ] = resolution.resolved_in

            return editor.repo.change(identifier, update)

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    @app.get("/")
    def index():
        return FileResponse(
            ROOT / "web" / "index.html", headers={"Cache-Control": "no-store"}
        )

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("AIEDIT_PORT", "8775")),
        log_level="warning",
    )
