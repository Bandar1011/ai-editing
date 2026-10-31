# AI Editing

A local video workspace for Codex: transcribe one clip, shape the story, render a plain cut, then review each encoded version with its own captions and timecoded feedback.

## Run on this Mac

```sh
uv run python scripts/doctor.py
./start.sh
```

Open **http://127.0.0.1:8775**. Import a video through the browser or give Codex its absolute file path. The app and chat use the same revision-checked API.

## What works

- Original footage is copied into a separate source folder and stays unchanged.
- Local multilingual whisper.cpp transcription produces a source-time transcript in JSON and SRT, separate from editable captions.
- Silence detection, manual source-time cuts, draggable boundaries, restore switches, undo/redo, and transcript-driven “Cut speech” actions.
- Editable caption wording, timing, size, position, and UTF-8 SRT import. Arabic and other spoken languages are retained.
- A project brief and reference/asset provenance records.
- Plain and captioned H.264/AAC exports, preserving native aspect ratio and frame rate. Captions are remapped to the edited timeline.
- Each version keeps its own MP4, SRT, SHA-256 checksum, edit snapshot, source ranges, brief, and asset-source manifest. Later edits do not change earlier exports.
- Encoded-version playback and timecoded notes recording the requested change and reason. Link a correction to a later export. Search feedback across projects; one-edit notes and reusable preferences are distinct.
- Agent CLI, local job status, recovery after interrupted jobs, and protection against overwriting concurrent browser edits.

This version handles one source clip per project. Target duration/format fields describe the brief; they do not automatically crop or shorten footage. Automatic retake selection, generative B-roll, presenter matting, motion graphics, music mixing, and multi-clip composition are future extensions. Speech recognition needs human review, especially names, fast speech, and noisy recordings. In-browser caption placement is approximate; review the encoded candidate before sharing.

## Fresh installation

Python 3.12+, [uv](https://docs.astral.sh/uv/), FFmpeg with libass, and [whisper.cpp](https://github.com/ggml-org/whisper.cpp) are required. On Apple Silicon macOS:

```sh
brew install uv ffmpeg-full whisper.cpp
uv sync --locked --group dev
uv run python scripts/setup_model.py
uv run python scripts/doctor.py
./start.sh
```

Model setup downloads the official multilingual Whisper base model and verifies its checksum. `AIEDIT_MODEL` can select another compatible local model. The app prefers Homebrew's `ffmpeg-full` for caption support, then falls back to `PATH`. Linux can use distribution FFmpeg with libass and an installed whisper.cpp CLI.

Optional environment variables: `AIEDIT_PORT` (default `8775`), `AIEDIT_DATA` (default `.aiedit/`), `AIEDIT_MODEL`, and `AIEDIT_URL` for the agent client. The server always binds to `127.0.0.1`. Local API documentation is at `/docs`.

## Direct from chat or terminal

```sh
python3 scripts/editor.py import /absolute/path/clip.mp4
python3 scripts/editor.py get PROJECT_ID
python3 scripts/editor.py transcribe PROJECT_ID --language auto
python3 scripts/editor.py silence PROJECT_ID --minimum 0.55 --padding 0.12
python3 scripts/editor.py export PROJECT_ID --no-subtitles --label "Story review"
python3 scripts/editor.py export PROJECT_ID --label "Caption review"
python3 scripts/editor.py history "caption placement" --reusable
```

Operations are asynchronous: poll `get` until the relevant `jobs` entry is `done`, and report `error` messages. Wait for one operation to finish before starting another for that project. Silence thresholds identify quiet audio, not delivery quality or false starts.

For custom decisions, fetch the latest project and save an Edit JSON file containing `base_revision`, `name`, `cuts`, `subtitles`, `subtitle_style`, `brief`, and `references`:

```sh
python3 scripts/editor.py save PROJECT_ID --file /absolute/path/edit.json
python3 scripts/editor.py review PROJECT_ID --file /absolute/path/note.json
python3 scripts/editor.py resolve PROJECT_ID --note-id NOTE_ID --file /absolute/path/resolution.json
```

A note contains `export_file`, `time` (seconds on that export), `change`, `reason`, and `scope` (`this_edit` or `reusable`). A resolution contains `resolved_in`, the filename of a later export; `null` reopens it. An HTTP 409 requires reading and reconciling the latest project. Keep source times on cuts and captions; do not shift them by removed time yourself.

## Files and privacy

```text
aiedit/             Media processing, timelines, persistence, HTTP API
web/                Browser editor; no frontend build step
scripts/            Agent client, doctor, model setup, generated demo
templates/brief.md  Starting brief for a real clip
docs/workflow.md    Editing process and tool selection
.aiedit/            Local-only data, ignored by Git
  models/
  projects/<id>/
    source/         Preserved imported original
    working/        Proxy, waveform, source transcript
    references/     Space for local supporting assets
    exports/        Immutable videos, captions, manifests
    history/        Earlier project revisions
    project.json    Current decisions, brief, references, reviews
```

The top-level `footage/`, `references/`, `working/`, and `exports/` folders are optional local staging areas and ignored by Git. Media, transcripts, models, and review notes are never part of the code repository. Back up `.aiedit/` separately to retain projects. There are no cloud inference calls, external API keys, or automatic publishing. Remembering feedback stores local history; it does not train a model or automatically apply preferences.

## Verify

```sh
uv run --group dev pytest -q
node --check web/app.js
```

Tests generate synthetic footage and exercise real FFmpeg decoding, cuts, burned captions, original preservation, range playback, revision conflicts, immutable export bundles, source transcripts, and feedback search. CI does not need personal footage or a speech-model download.

On macOS, `uv run python scripts/create_demo.py` makes a clearly generated sample using the system voice and FFmpeg. Import the printed path to try the workflow. It is not user footage.

The workflow is adapted from [George Wang's editing resource pack](https://246bfcda.ht-ml.app/). The starting editor foundation comes from this user's existing Local Cut workspace; this repository evolves it independently. See [workflow notes](docs/workflow.md) for the focused tool choices.
