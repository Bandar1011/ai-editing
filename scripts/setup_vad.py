"""Install the checksum-verified local Silero speech detector used for tighter cuts."""

import hashlib
import urllib.request
from pathlib import Path

target = Path(__file__).resolve().parent.parent / ".aiedit/models/ggml-silero-v6.2.0.bin"
expected = "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
    print("Local speech detector ready (checksum verified).")
else:
    url = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(2_000_000)
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("Speech detector checksum mismatch; existing model was kept.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
    print("Local speech detector installed (checksum verified).")
