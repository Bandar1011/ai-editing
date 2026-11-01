"""Import a local asset inbox without moving originals; print items for the agent to inspect/tag."""

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aiedit.assets import SUPPORTED

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("inbox", nargs="?", type=Path, default=ROOT / "references/inbox")
args = parser.parse_args()
base = os.environ.get("AIEDIT_URL", "http://127.0.0.1:8775")
try:
    known = json.load(urllib.request.urlopen(base + "/api/assets", timeout=30))
    hashes = {a["sha256"] for a in known}
    imported = []
    for source in sorted(args.inbox.expanduser().resolve().rglob("*")):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED:
            continue
        with source.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        if checksum in hashes:
            continue
        request = urllib.request.Request(
            base + "/api/assets/import",
            method="POST",
            data=json.dumps({"path": str(source), "source_kind": "local"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        imported.append(json.load(urllib.request.urlopen(request, timeout=60)))
        hashes.add(checksum)
    print(
        json.dumps(
            {
                "imported": imported,
                "next_step": "Inspect each asset, then tag its content, mood, intended use, source, and rights through the asset API.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
except (OSError, ValueError) as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
