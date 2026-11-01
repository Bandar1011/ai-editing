"""Check the real local binaries and model without importing footage."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aiedit.media import binary


def main():
    failed = False
    print(
        "Optional downloads: "
        + (shutil.which("yt-dlp") or "install yt-dlp for linked media")
    )
    for name in ("ffmpeg", "ffprobe", "whisper-cli"):
        try:
            path = binary(name)
            result = subprocess.run(
                [path, "-version" if name != "whisper-cli" else "--help"],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout)[-800:])
            if name == "whisper-cli" and any(
                flag not in result.stdout + result.stderr
                for flag in ("--dtw", "-nfa", "--output-json-full")
            ):
                raise RuntimeError(
                    "Update whisper.cpp: DTW, no-flash-attention, and full JSON output are required."
                )
            print(f"OK {name}: {path}")
            if name == "ffmpeg":
                filters = subprocess.run(
                    [path, "-hide_banner", "-filters"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if " ass " not in filters.stdout:
                    raise RuntimeError(
                        "This FFmpeg build lacks libass for captions. Use ffmpeg-full on macOS."
                    )
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"MISSING {name}: {exc}")
            failed = True
    model = Path(os.environ.get("AIEDIT_MODEL", ROOT / ".aiedit/models/ggml-base.bin"))
    if model.is_file():
        with model.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha1").hexdigest()
        if digest == "465707469ff3a37a2b9b8d8f89f2f99de7299dac":
            print(f"OK verified multilingual base model: {model}")
        elif os.environ.get("AIEDIT_MODEL"):
            print(
                f"OK custom model selected: {model} (base-model checksum not applicable)"
            )
        else:
            print(
                "MISSING valid base model: remove the damaged file and run scripts/setup_model.py"
            )
            failed = True
    else:
        print("MISSING speech model: uv run python scripts/setup_model.py")
        failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
