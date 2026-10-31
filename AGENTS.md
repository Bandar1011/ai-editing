# AI Editing

Build and operate this local, transcript-first editing workspace. Start with one clip, a source-timestamped transcript, and a plain story cut. Add captions and purposeful visuals after reviewing the story. The resource brief is summarized in `docs/workflow.md`.

- Run `./start.sh`; the app binds to `127.0.0.1:8775`. Use `python3 scripts/editor.py` for chat-driven edits through the same API as the browser.
- Keep source media unchanged. `.aiedit/` contains private media, transcripts, models, working files, export snapshots, and feedback; never commit it. All media processing and recognition stay local.
- Source timestamps are seconds on the original clip. Cuts remove intervals. Caption exports are mapped to the edited timeline. Keep native aspect ratio and frame rate unless the user asks otherwise.
- Read the latest revision before saving. Preserve manual cuts, restored ranges, and human caption corrections. Reconcile HTTP 409 conflicts; never overwrite another editor's work blindly.
- An export is an immutable review candidate with a complete edit snapshot and its own captions. Feedback must identify the exact export, timeline position, change, and reason. A one-edit note is not a reusable preference.
- Amplitude detects silence, not false starts or meaning. Review the transcript and listen to joins before claiming a story cut is good. Do not invent spoken words, screenshots, or asset provenance.
- Use subprocess argument arrays, validate intervals and filenames, and scope media serving to project IDs. Preserve loopback-only access and same-origin writes.
- Verify changes with `uv run --group dev pytest -q`, `node --check web/app.js`, and visible browser checks for UI changes. Tests use generated media; personal footage stays out of CI.
- Do not publish finished videos or create paid/cloud integrations unless requested. Optional motion, matting, music, and asset tools should be added when a specific clip needs them.
