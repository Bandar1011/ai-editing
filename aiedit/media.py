"""Local media operations. No shell command interpolation or cloud processing."""

import json
import re
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path

from .timeline import ass_text, kept_ranges, parse_srt, remap_subtitles


def binary(name: str) -> str:
    for root in (
        Path("/opt/homebrew/opt/ffmpeg-full/bin"),
        Path("/usr/local/opt/ffmpeg-full/bin"),
    ):
        if name in ("ffmpeg", "ffprobe") and (root / name).is_file():
            return str(root / name)
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is not installed.")
    return path


def run(args: list[str], *, cwd: Path | None = None, timeout: int = 3600) -> str:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        detail = (result.stderr or result.stdout)[-4000:]
        raise RuntimeError(f"Media operation failed: {detail}")
    return result.stdout


def probe(source: Path) -> dict:
    raw = json.loads(
        run(
            [
                binary("ffprobe"),
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(source),
            ],
            timeout=30,
        )
    )
    video = next((s for s in raw["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("This file does not contain a video stream.")
    duration = float(
        raw.get("format", {}).get("duration") or video.get("duration") or 0
    )
    if not 0 < duration < 86400:
        raise ValueError(
            "The video has no usable duration, or is longer than 24 hours."
        )
    width, height = int(video["width"]), int(video["height"])
    rotation = next(
        (
            abs(int(s.get("rotation", 0))) % 180
            for s in video.get("side_data_list", [])
            if "rotation" in s
        ),
        0,
    )
    if rotation == 90:
        width, height = height, width
    try:
        fps = float(Fraction(video.get("avg_frame_rate") or "30/1") or 30)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": any(s["codec_type"] == "audio" for s in raw["streams"]),
    }


def make_proxy(source: Path, directory: Path, audio: bool) -> None:
    run(
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(directory / "preview.mp4"),
        ]
    )
    if audio:
        run(
            [
                binary("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-filter_complex",
                "aformat=channel_layouts=mono,showwavespic=s=1600x120:colors=0x8ba7a1",
                "-frames:v",
                "1",
                str(directory / "waveform.png"),
            ]
        )


def detect_silence(
    source: Path, duration: float, threshold: float, minimum: float, padding: float
) -> list[dict]:
    result = subprocess.run(
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-vn",
            "-af",
            f"silencedetect=noise={threshold}dB:d={minimum}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:])
    cuts = []
    start = None
    for match in re.finditer(r"silence_(start|end):\s*([\d.eE+-]+)", result.stderr):
        value = float(match.group(2))
        if match.group(1) == "start":
            start = value
        elif start is not None:
            left = 0 if start < 0.05 else start + padding
            right = duration if value >= duration - 0.05 else value - padding
            if right - left >= 0.04:
                cuts.append(
                    {
                        "id": uuid.uuid4().hex[:10],
                        "start": round(max(0, left), 3),
                        "end": round(min(duration, right), 3),
                        "enabled": True,
                        "kind": "silence",
                    }
                )
            start = None
    if start is not None and duration - start - padding > 0.04:
        cuts.append(
            {
                "id": uuid.uuid4().hex[:10],
                "start": round(max(0, start + padding), 3),
                "end": duration,
                "enabled": True,
                "kind": "silence",
            }
        )
    if sum(b - a for a, b in kept_ranges(duration, cuts)) < 0.1:
        raise ValueError(
            "The whole recording was detected as quiet. Lower the threshold and try again; your existing cuts were kept."
        )
    return cuts


def transcribe(source: Path, directory: Path, model: Path, language: str) -> list[dict]:
    if not model.is_file():
        raise ValueError(
            "The local speech model is missing. Run: uv run python scripts/setup_model.py"
        )
    wav = directory / "speech.wav"
    prefix = directory / "speech"
    run(
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
    )
    run(
        [
            binary("whisper-cli"),
            "-m",
            str(model),
            "-f",
            str(wav),
            "-l",
            language,
            "-t",
            "4",
            "-ml",
            "42",
            "-sow",
            "-osrt",
            "-of",
            str(prefix),
            "-sns",
        ],
        timeout=14400,
    )
    return parse_srt(prefix.with_suffix(".srt").read_text(encoding="utf-8-sig"))


def export_video(
    project: dict, source: Path, output_dir: Path, burn_subtitles: bool
) -> Path:
    kept = kept_ranges(project["media"]["duration"], project["cuts"])
    if not kept:
        raise ValueError("There is no video left to export. Restore a cut first.")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{uuid.uuid4().hex[:10]}.mp4"
    audio = project["media"]["has_audio"]
    filters, concat = [], []
    for i, (start, end) in enumerate(kept):
        filters.append(
            f"[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{i}]"
        )
        concat.append(f"[v{i}]")
        if audio:
            tail = max(0, end - start - 0.015)
            filters.append(
                f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.015,afade=t=out:st={tail:.6f}:d=0.015[a{i}]"
            )
            concat.append(f"[a{i}]")
    filters.append(
        "".join(concat)
        + f"concat=n={len(kept)}:v=1:a={int(audio)}[vcat]"
        + ("[aout]" if audio else "")
    )
    cues = remap_subtitles(project["subtitles"], kept)
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
    if burn_subtitles and cues:
        caption_path = output_dir / f"{output.stem}.ass"
        caption_path.write_text(
            ass_text(
                cues,
                project["media"]["width"],
                project["media"]["height"],
                project["subtitle_style"],
            ),
            encoding="utf-8",
        )
        vf += f",ass=filename={caption_path.name}"
    filters.append(f"[vcat]{vf}[vout]")
    command = [
        binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        str(source),
        "-filter_complex_threads",
        "2",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
    ]
    if audio:
        command += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ]
    run(command, cwd=output_dir, timeout=14400)
    probe(output)
    return output
