"""Local media operations. No shell command interpolation or cloud processing."""

import json
import os
import re
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path

from .story import aligned_words, bound_words, short_captions
from .timeline import kept_ranges, parse_srt


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


def sdr_filter(source: Path) -> str:
    """Convert HDR camera footage before adding SDR captions or references."""
    raw = json.loads(run([
        binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_transfer", "-of", "json", str(source),
    ], timeout=30))
    transfer = raw["streams"][0].get("color_transfer")
    if transfer not in ("arib-std-b67", "smpte2084"):
        return ""
    peak = 10 if transfer == "arib-std-b67" else 0
    return (
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        f"tonemap=tonemap=hable:desat=0:peak={peak},"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,sidedata=mode=delete"
    )


def make_proxy(source: Path, directory: Path, audio: bool) -> None:
    tone = sdr_filter(source)
    scaling = "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2"
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
            scaling + ("," + tone if tone else ""),
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
    directory.mkdir(parents=True, exist_ok=True)
    wav, prefix = directory / "speech.wav", directory / "speech"
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
    # Flash attention disables DTW in whisper.cpp; explicitly disable it.
    preset = os.environ.get("AIEDIT_DTW_MODEL")
    if not preset:
        model_name = model.stem.removeprefix("ggml-")
        match = re.match(r"^(tiny|base|small|medium)(\.en)?", model_name)
        large = re.match(r"^large[-.]v([123])([-\.]turbo)?", model_name)
        preset = (
            match.group()
            if match
            else (
                ("large.v" + large[1] + (".turbo" if large[2] else ""))
                if large
                else None
            )
        )
    if not preset:
        raise ValueError(
            "Set AIEDIT_DTW_MODEL to the matching whisper.cpp alignment preset for this custom model."
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
            "2",
            "--dtw",
            preset,
            "-nfa",
            "-ojf",
            "-osrt",
            "-of",
            str(prefix),
            "-sns",
        ],
        timeout=14400,
    )
    raw = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
    duration = probe(source)["duration"]
    words = bound_words(aligned_words(raw), duration)
    if not words:
        raise ValueError(
            "No speech was recognized. Check the audio before generating an edit."
        )
    transcript = {
        "language": raw.get("result", {}).get("language", language),
        "timing_method": "whisper.cpp DTW token alignment; word boundaries are alignment estimates",
        "words": words,
        "cues": [
            dict(c, end=min(duration, c["end"]))
            for c in parse_srt(
                prefix.with_suffix(".srt").read_text(encoding="utf-8-sig")
            )
            if c["start"] < duration
        ],
    }
    (directory / "word-transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"
    )
    return short_captions(words)


def audio_quality(source: Path, start: float, end: float) -> dict:
    import array

    raw = subprocess.run(
        [
            binary("ffmpeg"),
            "-v",
            "error",
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        timeout=60,
        check=True,
    ).stdout
    samples = array.array("h", raw)
    if not samples:
        return {"clipped_fraction": 0.0}
    return {
        "clipped_fraction": round(
            sum(abs(s) >= 32700 for s in samples) / len(samples), 5
        )
    }


def export_video(
    project: dict,
    source: Path,
    output_dir: Path,
    burn_subtitles: bool,
    assets=None,
    plain=False,
    format="source",
) -> Path:
    from .render import export_video as render

    return render(project, source, output_dir, burn_subtitles, assets, plain, format)
