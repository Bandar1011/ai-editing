"""Local asset library. Captures and downloads are preserved with provenance."""

import hashlib
import ipaddress
import json
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import media

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED = IMAGES | {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
}


def valid_url(url):
    if not url:
        return
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Use a complete http/https source URL without credentials.")


class AssetLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, asset_id):
        if not re.fullmatch(r"[a-f0-9]{12}", asset_id):
            raise ValueError("Invalid asset ID.")
        return self.root / asset_id

    def get(self, asset_id):
        try:
            return json.loads((self.directory(asset_id) / "asset.json").read_text())
        except FileNotFoundError:
            raise ValueError("Asset not found in the local library.")

    def path(self, asset_id):
        asset = self.get(asset_id)
        return self.directory(asset_id) / asset["file"]

    def list(self, q="", kind=""):
        result = []
        for path in self.root.glob("*/asset.json"):
            asset = json.loads(path.read_text())
            searchable = " ".join(
                [asset["name"], asset["description"], *asset["tags"]]
            ).casefold()
            if (not kind or asset["kind"] == kind) and all(
                t in searchable for t in q.casefold().split()
            ):
                result.append(asset)
        return sorted(result, key=lambda a: a["created_at"], reverse=True)

    def import_file(
        self,
        source,
        *,
        name="",
        source_url="",
        source_kind="local",
        description="",
        tags=None,
        rights="",
        filename=None,
    ):
        source = Path(source).expanduser().resolve()
        suffix = Path(filename or source.name).suffix.lower()
        valid_url(source_url)
        if not source.is_file() or suffix not in SUPPORTED:
            raise ValueError("Choose a supported image, video, or audio file.")
        raw = json.loads(
            media.run(
                [
                    media.binary("ffprobe"),
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(source),
                ],
                timeout=30,
            )
        )
        video = next((s for s in raw["streams"] if s["codec_type"] == "video"), None)
        audio = next((s for s in raw["streams"] if s["codec_type"] == "audio"), None)
        kind = (
            "image"
            if suffix in IMAGES and video
            else "video"
            if video
            else "audio"
            if audio
            else None
        )
        if not kind:
            raise ValueError("This file has no usable image, video, or audio stream.")
        asset_id = uuid.uuid4().hex[:12]
        folder = self.directory(asset_id)
        folder.mkdir()
        target = folder / ("original" + suffix)
        shutil.copyfile(source, target)
        with target.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        asset = {
            "id": asset_id,
            "name": name.strip() or Path(filename or source.name).stem,
            "file": target.name,
            "kind": kind,
            "source_kind": source_kind,
            "source_url": source_url,
            "description": description,
            "tags": tags or [],
            "rights": rights,
            "sha256": checksum,
            "created_at": time.time(),
            "duration": float(raw.get("format", {}).get("duration") or 0),
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "has_audio": bool(audio),
        }
        sidecar = source.with_suffix(source.suffix + ".json")
        if source_kind == "simulator" and sidecar.is_file():
            provenance = json.loads(sidecar.read_text())
            if provenance.get("bundle") and provenance.get("source_sha256"):
                asset["capture"] = {
                    key: provenance.get(key)
                    for key in (
                        "bundle",
                        "source_head",
                        "source_sha256",
                        "source_branch",
                        "product_sha256",
                        "configuration",
                        "toolchain",
                        "sdk",
                        "sdk_version",
                        "architecture",
                        "captured_at",
                        "mode",
                        "reused_build",
                    )
                }
                (folder / "capture.json").write_text(
                    json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
                )
        metadata_path = folder / "asset.json"
        temporary = folder / "asset.tmp"
        temporary.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(metadata_path)
        return asset

    def update(self, asset_id, **metadata):
        with self.lock:
            asset = self.get(asset_id)
            asset.update(
                {
                    k: v
                    for k, v in metadata.items()
                    if k in {"name", "description", "tags", "rights"}
                }
            )
            target = self.directory(asset_id) / "asset.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(target)
            return asset

    def resolve(self, project):
        ids = {o["asset_id"] for o in project.get("overlays", [])}
        if project.get("music"):
            ids.add(project["music"]["asset_id"])
        return {i: {"metadata": self.get(i), "path": self.path(i)} for i in ids}

    def fetch(self, url, kind="audio", tags=None, rights=""):
        valid_url(url)
        host = urlparse(url).hostname
        if not host or any(
            not ipaddress.ip_address(address[4][0]).is_global
            for address in socket.getaddrinfo(host, None)
        ):
            raise ValueError("Use a public media URL.")
        folder = self.root.parent / "downloads" / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True)
        command = [
            media.binary("yt-dlp"),
            "--ignore-config",
            "--no-playlist",
            "--no-progress",
            "--max-filesize",
            "100M" if kind == "audio" else "50M",
            "--match-filter",
            "duration <= 600",
            "--ffmpeg-location",
            str(Path(media.binary("ffmpeg")).parent),
            "-o",
            str(folder / "source.%(ext)s"),
            "--write-info-json",
        ]
        if kind == "audio":
            command += ["-f", "bestaudio/best", "-x", "--audio-format", "m4a"]
        else:
            command += [
                "-f",
                "bestvideo[height<=1920][width<=1920]+bestaudio/best[height<=1920][width<=1920]",
                "--merge-output-format",
                "mp4",
            ]
        media.run([*command, "--", url], timeout=300)
        paths = [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED]
        if len(paths) != 1:
            raise ValueError(
                "No media was downloaded. The source may require login or exceed the 10-minute/100 MB limit."
            )
        info = next(folder.glob("*.info.json"), None)
        metadata = json.loads(info.read_text()) if info else {}
        return self.import_file(
            paths[0],
            name=metadata.get("title", ""),
            source_url=url,
            source_kind="download",
            description=metadata.get("description", "")[:4000],
            tags=tags,
            rights=rights,
        )
