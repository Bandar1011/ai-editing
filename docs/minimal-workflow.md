# Minimal reel workflow

The chat agent directs the edit. Local tools execute it and the browser keeps every decision reviewable. A source clip is never modified or published automatically.

The style reference is [Aiden Johnston's reel](https://www.instagram.com/reel/DegOQG6Tydw/): hooks, word-timed short captions, hard cuts, a labeled B-roll/music library, real browser references, occasional punch-ins, and a CTA. This workflow captures app references on the same laptop. It uses the installed local whisper.cpp alignment engine in place of the reel's WhisperX setup.

## First cut

```sh
python3 scripts/editor.py import /absolute/path/clip.mp4
python3 scripts/editor.py get PROJECT_ID
python3 scripts/editor.py prepare PROJECT_ID --language auto --max-words 3
```

Wait for the preview job before preparing; poll `get` until the preparation job is `done`. Preparation:

- Runs the installed whisper.cpp engine with DTW alignment and flash attention disabled. The model's word boundaries are estimates to review against the audio.
- Keeps the raw, source-timed transcript and word confidence separate from captions.
- Groups captions into 1–3 words without crossing cut boundaries. It preserves the spoken language; uppercase styling leaves Arabic intact.
- Detects quiet intervals and gaps between recognized utterances, retaining breathing room. Recognition gaps help when background audio masks silence. Missing/incorrect recognition can still create bad cuts; listen to every join.
- Removes isolated hesitation utterances such as “um”; meaningful words such as “like” are not globally stripped.
- Finds nearby repeated utterances and unfinished matching starts. It compares completeness, recognition confidence, filler count, and clipping. Clear exact retries can be selected automatically. Changed wording, ties, and uncertain delivery remain for the agent or user to compare.
- Preserves manual cuts and restored sections. Existing human-caption edits require the explicit Generate action before replacement.

Choose a take after listening and inspecting the shot:

```sh
python3 scripts/editor.py take PROJECT_ID --retake-id GROUP_ID --selected 0 --reason "The first take finishes the sentence clearly; the second clips its final word."
```

Indices are zero-based. Omit `--selected` to retain both takes. A numerical score is evidence, not a claim that loudness or recognition confidence measures the best performance. Read the full surrounding transcript to preserve meaning. Do not manufacture an editorial reason.

## Hooks and the ending

```sh
python3 scripts/editor.py hooks "a focused work session"
python3 scripts/editor.py history "pacing captions" --reusable
```

The hook library contains original structural patterns and separately stored user-supplied performance. It does not claim that an unsourced template is proven or viral. Match the hook to the topic, available footage, and actual measured examples. Store the chosen opening, reason, and CTA in `story`. These guide source selection or the next recording; they do not fabricate narration.

Record a real example with `hook-add --file hook.json`:

```json
{"text":"My actual published opening", "topic":"focus", "source_url":"https://example.com/reel", "views":1200, "retention":0.52, "notes":"Measured values supplied by the creator"}
```

## Asset inbox and mood library

```sh
uv run python scripts/ingest_assets.py /absolute/path/inbox
python3 scripts/editor.py assets "calm app"
python3 scripts/editor.py asset-import /absolute/path/capture.png --source-kind web --source-url https://example.com --description "The real feature being explained" --tags "app,reference"
python3 scripts/editor.py asset-fetch https://example.com/media --kind audio --tags "calm,tutorial"
python3 scripts/editor.py asset-job JOB_ID
```

Inbox import deduplicates by content checksum and preserves originals. Inspect images or representative video frames, listen where necessary, and add descriptive tags, mood, purpose, source, and rights through `PUT /api/assets/ASSET_ID`. File extension alone is not semantic classification. Asset search uses names, descriptions, and tags.

Downloads use the installed yt-dlp without browser cookies or user configuration. They are bounded to one item, ten minutes of media, a five-minute transfer, and a 100 MB working-directory budget. Sources without duration metadata are checked against the actual downloaded file. A failed login-protected or unsupported download is reported. Import an available local file instead of bypassing access controls. A downloader does not grant usage rights.

## Online references

When a spoken claim benefits from a web reference, open the actual relevant page using the connected browser tools. Verify its content visually, capture the real page or relevant visible region, and import the file with the exact source URL. Do not render a mock screenshot and call it evidence. Do not include unrelated private browser UI.

Place each imported reference on `overlays` with its source-time range and the reason it belongs there. Use a still for a static explanation. Use a short recording for a sequence of actions or animation. The agent chooses the source and range from the narration; no external model API runs inside the app server.

## App references on this Mac

Configure the target locally in `.aiedit/capture-settings.json` (ignored by Git):

```json
{"name":"My App Local", "repo":"/absolute/path/to/app", "scheme":"MyApp-Local", "bundle":"com.example.app.local", "cache_root":"/absolute/path/outside/source/AgentBuilds/MyApp"}
```

Read the target app's `AGENTS.md` first. Reuse existing registrations and its approved build/capture helper. This project's helper uses `AIEDIT_BUILD_WRAPPER`, defaulting to the installed `~/.local/bin/sandy-local-build`, with one owned Simulator lease, required SimSlim, and two compiler jobs. It never adopts another task's Simulator or falls back to unmanaged devices. A missing wrapper or refused resource guard is a real blocker.

For a launch-screen capture:

```sh
python3 scripts/editor.py capture-app --mode screenshot --description "The app's actual first screen"
python3 scripts/editor.py capture-app --mode video --seconds 4 --description "The app opening"
```

These are asset jobs; poll `asset-job`. The app helper builds once into its owned cache, then reuses only matching source/resource, toolchain, SDK, configuration, bundle, and product fingerprints. Captures retain a provenance sidecar outside the app repository; imported assets retain that sidecar too. It does not change app source, registrations, signing, or user containers.

For a specific screen or interaction, keep one lease while navigating:

```sh
uv run python scripts/capture_app.py --interactive --output /absolute/evidence/session.png
```

Wait for `session.session/ready.json`. Use its exact leased UDID with the available native UI tools, inspect the current hierarchy, and navigate the actual app. Submit new files into `session.session/requests/`:

```json
{"mode":"video", "seconds":5, "output":"/absolute/evidence/focus-flow.mp4"}
```

The matching file in `results/` progresses from `capturing` to `recording` when the first video frame is processed, then `done` or `error`. Begin the demonstrated interaction after `recording`. Screenshot requests finish directly. Multiple requests reuse the same build and lease. Close native UI-tool sessions, then create `session.session/DONE` to release the helper-owned session. It also expires after 15 minutes. Never remove lease locks or disable the host profile to force a capture.

Simulator visuals do not establish real Screen Time enforcement, purchases, or physical-device behavior. Use the app's appropriate device tests for those claims.

## Minimal composition

Save with the latest `base_revision`; preserve all unrelated fields. Production decisions use:

```json
{
  "overlays":[{"id":"reference1","asset_id":"0123456789ab","start":4.2,"end":7.2,"asset_in":0,"layout":"top","enabled":true,"purpose":"Show the feature being discussed"}],
  "punches":[{"id":"punch1","start":8,"end":10,"scale":1.1,"enabled":true}],
  "music":{"asset_id":"abcdef012345","volume":0.12,"offset":0,"duck":true,"enabled":true},
  "story":{"topic":"Focus timer","hook":"Chosen opening","hook_reason":"Why it matches the footage","cta":"The intended next step","app_bundle_id":"com.example.app"}
}
```

Overlays and punch-ins use source times; music is continuous on the edited timeline. Video references are muted by default. Set an overlay's `audio` to `true` and `volume` from 0 to 1 to include its audio. Audio-only assets can also be timed overlays, for effects or additional speech, with `start`, `end`, and `asset_in` controlling their source range. Their audio follows the same cuts as the main clip. Layouts are `top`, `bottom`, or `full`; top cards reserve space for the face, but placement still requires visual review. Use occasional 1.1× punch-ins when they add emphasis. Do not insert a change every three seconds mechanically. Music loops, fades at the ends, and can duck under the voice. Browser audio preview is approximate; encoded mixing is authoritative.

The browser edits one 9:16 vertical video. A fresh clip shows only video and original audio. Captions, overlays, effects, music, and added audio each get one track only while they have content. The timeline closes removed gaps. Click a clip, position the playhead, and use **Split** (⌘B), then **Delete** to remove a piece. Drag a clip edge to trim or extend it into available source footage; double-click an edge to restore it. **Restore full video** resets trimming and splits; undo restores the prior edit. Source media and source-timed captions and overlays remain unchanged. Split seams are persisted as `split_points` on the source, separately from the removal ranges in `cuts`. Panels open only when needed; the editor has no project picker or Edited/Original switch.

Browser exports pass `format: "vertical"`, producing an exact 9:16 center crop and retaining frame rate. Direct API calls default to `format: "source"` for compatibility; the CLI accepts `--format vertical`. Review the crop before exporting, especially for wide footage.

```sh
python3 scripts/editor.py export PROJECT_ID --format vertical --plain --label "Story review"
python3 scripts/editor.py export PROJECT_ID --format vertical --label "Captioned review"
```

Plain exports omit captions, overlays, punch-ins, and music. Final candidates freeze production decisions, asset provenance, captions, source ranges, and output checksums. Review the encoded file for missing words, bad joins, caption collisions, incorrect app screens, and audio balance. Save specific corrections against that export.
