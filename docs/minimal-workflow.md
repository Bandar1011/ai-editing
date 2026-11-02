# Minimal reel workflow

The connected assistant makes editorial decisions. The local application runs the repeated preparation and export steps, and the browser keeps each decision reviewable. A source clip is never modified or published automatically. Use one workflow: import, Prepare video, editorial decisions, live preview, export.

Read [editor.md](../editor.md) for editing instructions. [AGENTS.md](../AGENTS.md) covers engineering work; this document supplies commands and API examples.

Repeatable settings live in `aiedit/presets.py`: fixed title and caption sizes, two title lines maximum, 1–3 caption words, 120 ms minimum pauses, and 25 ms speech shoulders. Detection and rendering apply these consistently. The agent decides takes, caption corrections, title wording, reference type/content, and contextual placement; it intervenes in timing only for a demonstrated detector problem or specific feedback. Already approved edits remain unchanged.

The style reference is [Aiden Johnston's reel](https://www.instagram.com/reel/DegOQG6Tydw/): hooks, word-timed short captions, hard cuts, a labeled B-roll/music library, real browser references, occasional punch-ins, and a CTA. This workflow captures app references on the same laptop. It uses the installed local whisper.cpp alignment engine in place of the reel's WhisperX setup.

## First cut

```sh
python3 scripts/editor.py import /absolute/path/clip.mp4
python3 scripts/editor.py prepare PROJECT_ID --language auto --max-words 3 --wait
python3 scripts/editor.py context PROJECT_ID --start 60
```

Prepare can queue once behind the initial preview. The same pending request returns the same job; a conflicting operation returns 409. `--wait` follows that job and returns the first editorial context window when it completes. `context` returns at most 60 source seconds with `window.next_start` for continuation. `status PROJECT_ID` reads compact queue/stage state without fetching old export snapshots. A normal browser upload can be followed immediately by Prepare video. Preparation:

- Runs the installed whisper.cpp engine with DTW alignment and flash attention disabled. The model's word boundaries are estimates to review against the audio.
- Preserves no-audio and digital-silence recordings without recognition or new cuts. Existing edits remain intact.
- Reuses complete source-derived PCM, recognition, silence/VAD and retake artifacts when their dependencies match. Language/model/tool or relevant analysis settings invalidate the affected stage. Changing caption grouping does not rerun recognition. Incomplete/corrupt artifacts are recomputed; a processing failure never applies a partial edit. Raw analysis is separate from editable captions and project snapshots.
- Keeps the raw, source-timed transcript and word confidence separate from captions.
- Groups captions into 1–3 words without crossing cut boundaries. It preserves the spoken language; uppercase styling leaves Arabic intact.
- Uses the optional local Silero detector (`uv run python scripts/setup_vad.py`) plus 16 kHz mono quiet-interval analysis. Defaults retain 25 ms around speech and remove pauses of at least 120 ms. Without that model, preparation reports its fallback to recognition gaps. Breaths can still trigger speech activity; inspect waveforms and review every join. Missing/incorrect recognition can create bad cuts.
- Removes isolated hesitation utterances such as “um”; meaningful words such as “like” are not globally stripped.
- Finds nearby repeated utterances and unfinished matching starts. It compares completeness, recognition confidence, filler count, and clipping. Clear exact retries can be selected automatically. Changed wording, ties, and uncertain delivery remain for the agent or user to compare.
- Preserves manual cuts, restored sections and reviewed take decisions. An identical completed preparation leaves later human edits intact. Changed preparation settings cannot overwrite authored captions; use the explicit Generate action to replace them.

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

## Apply editorial decisions

Use `context` for the bounded source-time packet and `apply` for targeted decisions. Resolve uncertain takes first, then read updated context before correcting captions and placing title/reference assets. The app preserves untouched fields and applies each batch atomically with a revision check. It rejects a batch mixing take changes with caption/visual changes because caption IDs can change. Newly revealed take footage receives captions without replacing existing corrections.

```sh
python3 scripts/editor.py apply PROJECT_ID --file decisions.json
```

```json
{"base_revision":42,"caption_fixes":[{"id":"caption-id","text":"Correct spoken words"}],"story":{"topic":"The actual topic"}}
```

Use `take_choices` with `id`, `selected` and `reason` for a take batch. `overlays` upserts only submitted IDs; existing positions, sounds and other layers are preserved when omitted. Use an imported title card with `role: "title"` or a captured reference with `role: "reference"`. The deterministic title helper below owns formatting. A stale revision returns 409; reread context and reconcile it. The CLI returns a small acknowledgement instead of every historical export.

## Asset inbox and mood library

```sh
uv run python scripts/ingest_assets.py /absolute/path/inbox
python3 scripts/editor.py assets "calm app"
python3 scripts/editor.py asset-import /absolute/path/capture.png --source-kind web --source-url https://example.com --description "The real feature being explained" --tags "app,reference"
python3 scripts/editor.py asset-fetch https://example.com/media --kind audio --tags "calm,tutorial"
python3 scripts/editor.py asset-job JOB_ID
```

Inbox import deduplicates by content checksum and preserves originals. Inspect images or representative video frames, listen where necessary, and add descriptive tags, mood, purpose, source, and rights through `PUT /api/assets/ASSET_ID`. File extension alone is not semantic classification. Asset search uses names, descriptions, and tags.

The creator's default screenshot/B-roll entrance sound is **Bubble pop**, stored locally with the tag `default-reference-pop`. Find it with `python3 scripts/editor.py assets default-reference-pop`. Exactly one playable audio asset should have that tag. The default recipe comes from `GET /api/assets/reference-sound`, with the approved 35% volume and 0.10-second playback offset. The original file, selected asset ID, and rights notes stay in the private library.

The browser automatically attaches that sound when **Add overlay** creates a screenshot/B-roll reference. Assets explicitly tagged `title` or `graphic` use that type instead. In the overlay inspector, **Type** distinguishes Screenshot / B-roll, Title, and Graphic; **Pop sound** and **Pop volume** control the linked effect. It appears in Added audio; selecting it opens its reference, and Delete disables the sound without deleting the visual. Moving/trimming, disabling, removing, or undoing the reference also updates the sound. One reference plays one pop continuously from its first kept visible frame, even across speech cuts; the sound stops at the earlier of the audio's end or reference disappearance.

For API/chat additions, set `role: "reference"` on new screenshot/B-roll overlays and omit `entrance_sound` to receive the automatic default. Set `role: "title"` or `"graphic"` for other visuals, or explicitly set `entrance_sound: null` to opt out. The returned `entrance_sound` freezes the chosen local asset, offset, volume, and enabled state. Preserve that object on subsequent saves; omitted fields on existing IDs are preserved. Missing or ambiguous defaults fail a new reference save with a useful error. Legacy unclassified overlays and approved manual effects stay unchanged. Do not place an additional manual pop alongside an automatically attached one.

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

Use [the title-writing skill](../skills/reel-titles/SKILL.md), the saved profile analysis and relevant hook performance to choose a faithful opening. Revisit the profile only for a requested new style reference or updated performance research. Use a large top title for 2–3 seconds, matching the joined rounded white line backgrounds in [the user's title reference](https://www.tiktok.com/@bandar_h0/video/7661398997373930772). The selected font is Geeza Pro Regular, available on this Mac. The original published video's font metadata is unavailable; its Arabic letterforms were compared visually against installed fonts. Keep the spoken language. Generate a transparent card locally, then import it as an image overlay:

```sh
uv run scripts/title_card.py /absolute/private/path/title.png --line "First line" --line "Second line"
```

The helper uses the approved fixed title preset: Geeza Pro Regular, 129 px per 1080 frame width, up to two lines, and 2.5 edited seconds. Longer wording fails rather than shrinking or adding lines. It shapes locally with FFmpeg/libass and paints exact black using Pillow. Set only the frame `--width` normally; change font or size only for an explicit style request. Never redistribute system fonts. Import title assets with the `title` tag, and set their overlay `role: "title"` to exclude the reference pop. Place the card using its actual normalized dimensions without stretching. HLG titles use `white_nits: 1000`; ordinary references default to `203`. This changes graphics only. New projects also start with the approved caption style (52 at 1080 image height, Geeza Pro Regular, 4.5 outline); authored existing styles are preserved.

Save with the latest `base_revision`; preserve all unrelated fields. Production decisions use:

```json
{
  "overlays":[{"id":"reference1","asset_id":"0123456789ab","start":4.2,"end":7.2,"asset_in":0,"layout":"top","role":"reference","enabled":true,"purpose":"Show the feature being discussed"}],
  "punches":[{"id":"punch1","start":8,"end":10,"scale":1.1,"enabled":true}],
  "music":{"asset_id":"abcdef012345","volume":0.12,"offset":0,"duck":true,"enabled":true},
  "story":{"topic":"Focus timer","hook":"Chosen opening","hook_reason":"Why it matches the footage","cta":"The intended next step","app_bundle_id":"com.example.app"}
}
```

Overlays and punch-ins use source times; music is continuous on the edited timeline. Video references are muted by default. Set an overlay's `audio` to `true` and `volume` from 0 to 1 to include its audio. Audio-only assets can also be timed overlays, for effects or additional speech, with `start`, `end`, and `asset_in` controlling their source range. Their audio follows the same cuts as the main clip. Layouts are `top`, `bottom`, or `full`; top cards reserve space for the face, but placement still requires visual review. Use occasional 1.1× punch-ins when they add emphasis. Do not insert a change every three seconds mechanically. Music loops, fades at the ends, and can duck under the voice. Browser audio preview is approximate; encoded mixing is authoritative.

Inspect the real shot before placing a reference. Pointing and gaze indicate where an inset belongs; keep the face, hand, and captions visible. Use a focused real screenshot for a static reference and an actual browser/app recording for an interaction when the capture tool is available. Full-screen references require an editorial reason. A still spanning removed speech gaps is composed as one continuous overlay, preventing a camera flash at the join. Video assets retain their source-time skips; they are not flattened into a still.

The browser edits one 9:16 vertical video. A fresh clip shows only video and original audio. Captions, overlays, effects, music, and added audio each get one track only while they have content. The timeline closes removed gaps. Click a clip, position the playhead, and use **Split** (⌘B), then **Delete** to remove a piece. Drag a clip edge to trim or extend it into available source footage; double-click an edge to restore it. **Restore full video** resets trimming and splits; undo restores the prior edit. Source media and source-timed captions and overlays remain unchanged. Split seams are persisted as `split_points` on the source, separately from the removal ranges in `cuts`. Panels open only when needed; the editor has no project picker or Edited/Original switch.

Browser exports pass `format: "vertical"`, producing an exact 9:16 center crop at the source resolution and probed frame rate. The existing encoder uses that rate as constant output cadence, including for variable-rate sources; this optimization does not change that behavior. Direct API calls default to `format: "source"` for compatibility; the CLI accepts `--format vertical`. Review the crop before exporting, especially for wide footage. Preserve HLG/PQ color transfer and 10-bit depth in HEVC; do not automatically tone-map or add punch-ins. SDR graphics use 203-nit white in HDR without grading the underlying footage. A compatible HDR player/display is needed for faithful playback.

```sh
python3 scripts/editor.py export PROJECT_ID --format vertical --label "Final review" --wait
```

Review revisions in the browser without an export. Use `--plain` only for a requested or useful comparison; it omits captions, overlays, punch-ins, and music. Identical effective exports reuse verified MP4 bytes, excluding labels and project revisions from the render identity, while writing a fresh independent snapshot and SRT. Missing or corrupt cached exports are rendered again. Final candidates freeze production decisions, asset provenance, captions, source ranges, and output checksums. Review the encoded file for missing words, bad joins, caption collisions, incorrect app screens, and audio balance. Save specific corrections against that export.
