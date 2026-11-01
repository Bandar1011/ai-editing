"""Chat-agent client for the running local editor. Uses the same API as the UI."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "command",
    choices=[
        "health",
        "list",
        "import",
        "get",
        "save",
        "silence",
        "transcribe",
        "export",
        "review",
        "resolve",
        "history",
        "prepare",
        "assets",
        "asset-import",
        "asset-fetch",
        "asset-job",
        "capture-app",
        "take",
        "hooks",
        "hook-add",
    ],
)
parser.add_argument("value", nargs="?")
parser.add_argument("--file", type=Path)
parser.add_argument("--threshold", type=float, default=-35)
parser.add_argument("--minimum", type=float, default=0.55)
parser.add_argument("--padding", type=float, default=0.12)
parser.add_argument("--language", default="auto")
parser.add_argument("--no-subtitles", action="store_true")
parser.add_argument("--label", default="")
parser.add_argument("--reusable", action="store_true")
parser.add_argument("--note-id")
parser.add_argument("--plain", action="store_true")
parser.add_argument("--max-words", type=int, choices=[1, 2, 3], default=3)
parser.add_argument("--source-url", default="")
parser.add_argument(
    "--source-kind", choices=["local", "web", "simulator", "download"], default="local"
)
parser.add_argument("--description", default="")
parser.add_argument("--name", default="")
parser.add_argument("--tags", default="")
parser.add_argument("--rights", default="")
parser.add_argument("--kind", choices=["audio", "video", "image"], default="audio")
parser.add_argument("--mode", choices=["screenshot", "video"], default="screenshot")
parser.add_argument("--seconds", type=float, default=4)
parser.add_argument("--retake-id")
parser.add_argument("--selected", type=int, choices=[0, 1])
parser.add_argument(
    "--reason", default="Selected after reviewing delivery and meaning."
)
args = parser.parse_args()
base = os.environ.get("AIEDIT_URL", "http://127.0.0.1:8775")
route, method, body = "/api/health", "GET", None
if args.command == "list":
    route = "/api/projects"
elif args.command == "assets":
    import urllib.parse

    route = "/api/assets?" + urllib.parse.urlencode({"q": args.value or ""})
elif args.command == "asset-import":
    if not args.value:
        parser.error("asset-import requires a file path")
    route, method, body = (
        "/api/assets/import",
        "POST",
        {
            "path": str(Path(args.value).expanduser().resolve()),
            "name": args.name,
            "source_url": args.source_url,
            "source_kind": args.source_kind,
            "description": args.description,
            "tags": [s.strip() for s in args.tags.split(",") if s.strip()],
            "rights": args.rights,
        },
    )
elif args.command == "asset-fetch":
    route, method, body = (
        "/api/assets/fetch",
        "POST",
        {
            "url": args.value,
            "kind": args.kind,
            "tags": [s.strip() for s in args.tags.split(",") if s.strip()],
            "rights": args.rights,
        },
    )
elif args.command == "asset-job":
    if not args.value:
        parser.error("asset-job requires a job ID")
    route = "/api/assets/jobs/" + args.value
elif args.command == "capture-app":
    route, method, body = (
        "/api/assets/capture-app",
        "POST",
        {"mode": args.mode, "seconds": args.seconds, "description": args.description},
    )
elif args.command == "hooks":
    import urllib.parse

    route = "/api/hooks?" + urllib.parse.urlencode({"topic": args.value or ""})
elif args.command == "hook-add":
    if not args.file:
        parser.error("hook-add requires --file with hook/performance JSON")
    route, method, body = "/api/hooks", "POST", json.loads(args.file.read_text())
elif args.command == "import":
    if not args.value:
        parser.error("import requires the path to the supplied video")
    route, method, body = (
        "/api/projects/import",
        "POST",
        {"path": str(Path(args.value).expanduser().resolve())},
    )
elif args.command == "history":
    import urllib.parse

    route = "/api/history?" + urllib.parse.urlencode(
        {"q": args.value or "", "reusable": str(args.reusable).lower()}
    )
elif args.command not in ("health", "list"):
    if not args.value:
        parser.error("this command requires a project ID")
    route = f"/api/projects/{args.value}"
    if args.command == "save":
        if not args.file:
            parser.error(
                "save requires --file with an Edit JSON object, including base_revision"
            )
        method, body = "PUT", json.loads(args.file.read_text())
    elif args.command == "silence":
        route += "/silence"
        method, body = (
            "POST",
            {
                "threshold_db": args.threshold,
                "minimum": args.minimum,
                "padding": args.padding,
            },
        )
    elif args.command == "transcribe":
        route += "/transcribe"
        method, body = "POST", {"language": args.language}
    elif args.command == "prepare":
        route += "/prepare"
        method, body = "POST", {"language": args.language, "max_words": args.max_words}
    elif args.command == "take":
        if not args.retake_id:
            parser.error("take requires --retake-id")
        route += "/retakes/" + args.retake_id
        method, body = "POST", {"selected": args.selected, "reason": args.reason}
    elif args.command == "export":
        route += "/export"
        method, body = (
            "POST",
            {
                "burn_subtitles": not args.no_subtitles and not args.plain,
                "label": args.label,
                "plain": args.plain,
            },
        )
    elif args.command in ("review", "resolve"):
        if not args.file:
            parser.error(
                "review/resolve requires --file with the note or resolution JSON"
            )
        route += "/reviews"
        method = "POST"
        if args.command == "resolve":
            if not args.note_id:
                parser.error("resolve requires --note-id")
            route += "/" + args.note_id
            method = "PATCH"
        body = json.loads(args.file.read_text())
request = urllib.request.Request(
    base + route,
    data=json.dumps(body).encode() if body is not None else None,
    method=method,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False, indent=2))
except urllib.error.HTTPError as exc:
    print(exc.read().decode(), file=sys.stderr)
    sys.exit(1)
except urllib.error.URLError:
    print("Start the local editor first with ./start.sh", file=sys.stderr)
    sys.exit(1)
