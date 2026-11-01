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
- Local multilingual whisper.cpp transcription with DTW word alignment produces source-time words and a raw transcript, separate from editable 1–3-word captions.
- Silence detection, manual source-time cuts, draggable boundaries, restore switches, undo/redo, and transcript-driven “Cut speech” actions.
- Editable caption wording, timing, size, position, and UTF-8 SRT import. Arabic and other spoken languages are retained.
- One-click first cuts combine speech-gap and quiet-interval cuts, isolated hesitation removal, and evidence-based retake selection. Ambiguous deliveries remain reviewable.
- A project brief, original hook patterns, user-supplied performance history, and CTA planning.
- A searchable local asset/mood library, deduplicated inbox import, and bounded yt-dlp media downloads.
- Timed real screenshot/B-roll overlays, audio clips, optional punch-ins, and looping music with voice-priority ducking. Video-overlay audio is optional and has its own gain.
- A monochrome editor with a phone-sized 9:16 portrait preview, native landscape previews, and labeled source tracks for video, original audio, captions, overlays, effects, music, and added audio. Drag to select a source range, cut it, restore it, or undo. Timeline clips open their controls; timeline zoom supports precise work on longer clips.
- Same-laptop app screenshots/recordings through an owned Simulator lease and fingerprinted build reuse. Read the [capture requirements](docs/minimal-workflow.md#app-references-on-this-mac).
- Plain and captioned H.264/AAC exports, preserving native aspect ratio and frame rate. Captions are remapped to the edited timeline.
- Each version keeps its own MP4, SRT, SHA-256 checksum, edit snapshot, source ranges, brief, and asset-source manifest. Later edits do not change earlier exports.
- Encoded-version playback and timecoded notes recording the requested change and reason. Link a correction to a later export. Search feedback across projects; one-edit notes and reusable preferences are distinct.
- Agent CLI, local job status, recovery after interrupted jobs, and protection against overwriting concurrent browser edits.

Each project has one main talking-head clip plus image/video references and music. Target duration/format fields describe the brief; they do not automatically crop or shorten footage. Generative B-roll, presenter matting, and elaborate motion graphics are outside this minimal workflow. Recognition and retake scores need review, especially names, changed wording, intentional repetition, and noisy speech. Browser captions and mixing are approximate; the encoded candidate is authoritative.

## Fresh installation

Python 3.12+, [uv](https://docs.astral.sh/uv/), FFmpeg with libass, and [whisper.cpp](https://github.com/ggml-org/whisper.cpp) are required. On Apple Silicon macOS:

```sh
brew install uv ffmpeg-full whisper.cpp yt-dlp
uv sync --locked --group dev
uv run python scripts/setup_model.py
uv run python scripts/doctor.py
./start.sh
```

Model setup downloads the official multilingual Whisper base model and verifies its checksum. Word timing uses whisper.cpp DTW (`--dtw base -nfa -ojf`); the installed 1.9.5 CLI was exercised locally. No separate heavy alignment engine is required for the default model. `AIEDIT_MODEL` can select another compatible local model. The app prefers Homebrew's `ffmpeg-full` for caption support, then falls back to `PATH`. Linux can use distribution FFmpeg with libass and an installed whisper.cpp CLI.

Optional environment variables: `AIEDIT_PORT` (default `8775`), `AIEDIT_DATA` (default `.aiedit/`), `AIEDIT_MODEL`, `AIEDIT_DTW_MODEL` (matching alignment preset for custom models), and `AIEDIT_URL` for the agent client. The server always binds to `127.0.0.1`. Local API documentation is at `/docs`.

## Direct from chat or terminal

```sh
python3 scripts/editor.py import /absolute/path/clip.mp4
python3 scripts/editor.py get PROJECT_ID
python3 scripts/editor.py prepare PROJECT_ID --language auto --max-words 3
python3 scripts/editor.py transcribe PROJECT_ID --language auto
python3 scripts/editor.py silence PROJECT_ID --minimum 0.55 --padding 0.12
python3 scripts/editor.py export PROJECT_ID --plain --label "Story review"
python3 scripts/editor.py export PROJECT_ID --label "Caption review"
python3 scripts/editor.py history "caption placement" --reusable
```

Operations are asynchronous: poll `get` until the relevant `jobs` entry is `done`, and report `error` messages. Wait for one operation to finish before starting another for that project. Silence thresholds identify quiet audio, not delivery quality or false starts.

For custom decisions, fetch the latest project and save an Edit JSON file containing `base_revision`, `name`, `cuts`, `subtitles`, `subtitle_style`, `brief`, `references`, `overlays`, `punches`, `music`, and `story`:

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
  library/          Private assets, mood tags, and hook performance
  capture-settings.json  Machine-specific app capture target
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
node --check web/production.js
```

Tests generate synthetic footage and exercise real FFmpeg decoding, cuts, burned captions, original preservation, range playback, revision conflicts, immutable export bundles, source transcripts, and feedback search. CI does not need personal footage, a speech-model download, an Xcode installation, or a native Simulator. Capture guard tests and mocks prove their own scope; actual native captures require the local host prerequisites.

On macOS, `uv run python scripts/create_demo.py` makes a clearly generated sample using the system voice and FFmpeg. Add `--minimal` for a vertical sample with an unfinished retry and a web-reference cue. Import the printed path to try the workflow. It is not user footage.

The workflow is adapted from [George Wang's editing resource pack](https://246bfcda.ht-ml.app/). The starting editor foundation comes from this user's existing Local Cut workspace; this repository evolves it independently. See [workflow notes](docs/workflow.md) for the focused tool choices.

The complete agent recipe, asset commands, production JSON, and interactive same-laptop capture protocol are in [the minimal workflow guide](docs/minimal-workflow.md).
