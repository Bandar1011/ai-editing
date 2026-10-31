"""Download the official multilingual Whisper base model for on-device captions."""

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
target = ROOT / ".aiedit" / "models" / "ggml-base.bin"
expected = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"
if target.is_file():
    with target.open("rb") as handle:
        existing = hashlib.file_digest(handle, "sha1").hexdigest()
    if existing == expected:
        print(f"Speech model ready (checksum verified): {target}")
        sys.exit(0)
    print("Existing model failed verification. Downloading a verified replacement.")
target.parent.mkdir(parents=True, exist_ok=True)
url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
temp = target.with_suffix(".download")
digest = hashlib.sha1()
with urllib.request.urlopen(url, timeout=60) as response, temp.open("wb") as output:
    size = int(response.headers.get("Content-Length", 0))
    received, last = 0, -1
    while chunk := response.read(1024 * 1024):
        output.write(chunk)
        digest.update(chunk)
        received += len(chunk)
        progress = received * 10 // size if size else received // 20_000_000
        if progress != last:
            print(
                f"Downloaded {received / 1_000_000:.0f} MB"
                + (f" / {size / 1_000_000:.0f} MB" if size else ""),
                flush=True,
            )
            last = progress
if received < 100_000_000:
    raise RuntimeError("The model download was incomplete; run this command again.")
# Published checksum from the whisper.cpp model registry.
if digest.hexdigest() != expected:
    temp.unlink(missing_ok=True)
    raise RuntimeError("The speech model checksum did not match the published model.")
temp.replace(target)
print(f"Speech model ready: {target}")
