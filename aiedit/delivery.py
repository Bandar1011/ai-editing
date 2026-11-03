"""Share a pinned, current export using the local macOS AirDrop service."""

import hashlib
import json
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import Field

from .production import Strict

ROOT = Path(__file__).resolve().parent.parent
EDIT_FIELDS = (
    "cuts",
    "split_points",
    "subtitles",
    "subtitle_style",
    "overlays",
    "punches",
    "music",
    "story",
)


def matches_export(project, export):
    settings = export.get("render_settings", {})
    return (
        settings.get("format") == "vertical"
        and not settings.get("plain", True)
        and settings.get("burn_subtitles")
        == bool(project["subtitle_style"]["enabled"] and project["subtitles"])
        and export.get("source_sha256") == project.get("source_sha256")
        and all(
            export.get("edit_state", {}).get(key, [] if key == "split_points" else None)
            == project.get(key)
            for key in EDIT_FIELDS
        )
        and export.get("brief") == project.get("brief")
        and export.get("references") == project.get("references")
    )


class AirDropRequest(Strict):
    base_revision: int = Field(ge=1)
    file: str = Field(pattern=r"^[a-f0-9]{10}\.mp4$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class AirDrop:
    def __init__(self, editor):
        self.editor = editor
        self.lock = threading.RLock()
        self.requests = {}
        self.current = None
        self.closed = False

    def validate(self, identifier, filename, revision=None, checksum=False):
        with self.editor.repo.lock(identifier):
            project = self.editor.repo.load(identifier)
            if revision is not None and project["revision"] != revision:
                raise HTTPException(
                    409, "The edit changed. Read the latest project before sharing."
                )
            if any(
                j.get("status") in {"running", "queued"} or j.get("next_job_pending")
                for j in project["jobs"].values()
            ):
                raise HTTPException(
                    409, "Wait for processing to finish before sharing."
                )
            export = next(
                (e for e in project["exports"] if e["file"] == filename), None
            )
            if export is None:
                raise HTTPException(404, "Export not found.")
            if not matches_export(project, export):
                raise HTTPException(
                    409, "Create an export of the current edit before sharing."
                )
            folder = self.editor.repo.directory(identifier) / "exports"
            path = folder / filename
            if (
                not path.is_file()
                or path.is_symlink()
                or path.resolve().parent != folder.resolve()
            ):
                raise HTTPException(404, "Export file is missing.")
            if checksum:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != export["sha256"]:
                    raise ValueError(
                        "The export file changed. Create a new export before sharing."
                    )
            return path

    def start(self, identifier, options):
        with self.lock:
            key = (identifier, options.request_id)
            if key in self.requests:
                entry = self.requests[key]
                if entry["file"] != options.file:
                    raise HTTPException(
                        409, "This sharing request belongs to another export."
                    )
                return self.status(identifier, options.request_id)
            if self.closed:
                raise ValueError("Restart the editor before opening AirDrop.")
            if platform.system() != "Darwin":
                raise ValueError(
                    "AirDrop requires macOS. Download the exported video on a Mac."
                )
            if self.current:
                previous = self.status(*self.current)
                if previous["status"] in {"preparing", "choosing"}:
                    raise HTTPException(
                        409, "Finish or close the current AirDrop window first."
                    )
            self.validate(identifier, options.file, options.base_revision)
            folder = (
                self.editor.repo.directory(identifier)
                / "working"
                / "airdrop"
                / options.request_id
            )
            folder.mkdir(parents=True)
            self.requests[key] = {
                "file": options.file,
                "state_file": folder / "status.json",
                "status": "preparing",
                "message": "Preparing AirDrop",
                "process": None,
            }
            self.current = key
            try:
                self.editor.pool.submit(self.open, identifier, options)
            except Exception:
                self.requests[key].update(
                    status="error", message="AirDrop could not start. Try again."
                )
                raise
            return self.status(identifier, options.request_id)

    def open(self, identifier, options):
        key = (identifier, options.request_id)
        try:
            source = ROOT / "scripts" / "share_airdrop.swift"
            identity = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
            folder = self.editor.repo.root / "runtime" / "airdrop"
            folder.mkdir(parents=True, exist_ok=True)
            binary = folder / ("share-" + identity)
            if not binary.is_file():
                compiler = shutil.which("swiftc")
                if not compiler:
                    raise ValueError(
                        "Install Apple's command-line developer tools to use AirDrop."
                    )
                result = subprocess.run(
                    [
                        compiler,
                        "-parse-as-library",
                        str(source),
                        "-o",
                        str(binary),
                        "-module-cache-path",
                        str(folder / "module-cache"),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if result.returncode:
                    raise ValueError(
                        "The AirDrop helper could not be built. Check the local developer tools."
                    )
            path = self.validate(identifier, options.file, checksum=True)
            with self.lock:
                if self.closed:
                    raise ValueError("AirDrop stopped when the editor closed.")
                entry = self.requests[key]
                entry["process"] = subprocess.Popen(
                    [str(binary), str(path), str(entry["state_file"])],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as error:
            with self.lock:
                self.requests[key].update(
                    status="error", message=str(getattr(error, "detail", error))
                )

    def status(self, identifier, request_id):
        self.editor.repo.directory(identifier)
        if not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise HTTPException(404, "AirDrop request not found.")
        with self.lock:
            entry = self.requests.get((identifier, request_id))
            if not entry:
                raise HTTPException(
                    404, "AirDrop request not found. Try sharing again."
                )
            try:
                raw = entry["state_file"].read_text()
                update = json.loads(raw) if len(raw) < 4000 else {}
                if update.get("status") in {"choosing", "closed", "cancelled", "error"}:
                    entry.update(
                        status=update["status"],
                        message=str(update.get("message", ""))[:500],
                    )
            except (OSError, ValueError):
                pass
            process = entry["process"]
            if (
                process is not None
                and process.poll() is not None
                and entry["status"] in {"preparing", "choosing"}
            ):
                entry.update(
                    status="error",
                    message="AirDrop closed without completing. Try again.",
                )
            return {
                "id": request_id,
                "project_id": identifier,
                "file": entry["file"],
                "status": entry["status"],
                "message": entry["message"],
            }

    def close(self):
        with self.lock:
            self.closed = True
            for entry in self.requests.values():
                process = entry["process"]
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)


def router(airdrop):
    api = APIRouter()

    @api.post("/api/projects/{identifier}/airdrop")
    def send(identifier: str, options: AirDropRequest):
        return airdrop.start(identifier, options)

    @api.get("/api/projects/{identifier}/airdrop/{request_id}")
    def status(identifier: str, request_id: str):
        return airdrop.status(identifier, request_id)

    return api
