# Reels Factory

Build and operate this local, transcript-first editing workspace. Start with one clip, a source-timestamped transcript, and a plain story cut. Add captions and purposeful visuals after reviewing the story. The resource brief is summarized in `docs/workflow.md`.

- Run `./start.sh`; the app binds to `127.0.0.1:8775`. Use `python3 scripts/editor.py` for chat-driven edits through the same API as the browser.
- Keep source media unchanged. `.aiedit/` contains private media, transcripts, models, working files, export snapshots, and feedback; never commit its contents except the storage README and empty `projects/.gitkeep` placeholder. All media processing and recognition stay local.
- Source timestamps are seconds on the original clip. Cuts remove intervals. Caption exports are mapped to the edited timeline. Keep native aspect ratio and frame rate unless the user asks otherwise.
- Read the latest revision before saving. Preserve manual cuts, restored ranges, and human caption corrections. Reconcile HTTP 409 conflicts; never overwrite another editor's work blindly.
- An export is an immutable review candidate with a complete edit snapshot and its own captions. Feedback must identify the exact export, timeline position, change, and reason. A one-edit note is not a reusable preference.
- Amplitude detects silence, not false starts or meaning. Review the transcript and listen to joins before claiming a story cut is good. Do not invent spoken words, screenshots, or asset provenance.
- Use subprocess argument arrays, validate intervals and filenames, and scope media serving to project IDs. Preserve loopback-only access and same-origin writes.
- Verify changes with `uv run --group dev pytest -q`, `node --check web/app.js`, `node --test tests/*.test.mjs`, and visible browser checks for UI changes. Tests use generated media; personal footage stays out of CI.
- Do not publish finished videos or create paid/cloud integrations unless requested. Keep the user's minimal style: 1–3 words per caption, speech-gap hard cuts, the better repeated take, real references, and restrained visual treatment.
- Keep the editor monochrome, minimal, and focused on one 9:16 vertical video. Do not show a project/demo picker, a Cuts inspector, or an Edited/Original switch. Start with video and original audio; show one additional row per type only while captions, overlays, effects, music, or added audio actually exist. Extra controls open on demand. The joined timeline uses Split and Delete with linked video/audio clips; draggable edges recover trimmed source footage, double-click restores an edge, and Restore full video and undo remain available. Browser exports are vertical, preserving frame rate. Keep direct action labels and omit decorative copy.
- The header shows Reels Factory without a project-name field or Project settings. Auto Edit, Media, and Captions belong inside one collapsible right panel; a left arrow reopens it. Timeline and preview layer selections stay linked. User-added captions and visual overlays can be dragged in the preview; store their centres as normalized x/y coordinates and preserve them in exports. Keep Export separate from the tools tabs.

## Editing a reel from chat

Follow `docs/minimal-workflow.md`. Prepare the clip through the API, read the raw transcript and word times, and review every retake group in context. Select the better delivery using actual audio/frames; preserve changed meaning and intentional repetition. Resolve uncertain candidates yourself from evidence when possible, without asking the user to choose every routine edit. Recognition confidence alone does not establish quality.

Read relevant reusable feedback and hook performance before planning the opening/CTA. Hooks and CTA plans do not authorize invented speech. Ingest local assets, inspect their actual content, and label/search B-roll and music by subject, mood, purpose, source, and rights.

For useful web references, use browser tools to capture the real page and store the exact URL. For an app demonstration, use a simulator on this laptop. Read the target repo's current instructions, respect its owned native lane/profile, and use the configured local capture helper. Select a screenshot for static information or a short recording for actions/animation. A specific screen needs an interactive leased session; a fresh launch capture alone does not demonstrate that screen. Preserve capture provenance and release the owned lease after related captures.

Keep original media, captured app evidence, local paths, and machine-specific capture settings out of Git. App captures are source material; never imply that a Simulator proves real-device enforcement or purchases. Render a plain cut and a final candidate, check the exact encoded files, and preserve corrections with their versions.
