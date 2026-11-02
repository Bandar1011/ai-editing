# Reels Factory editing instructions

Follow this file when editing videos. Coding and maintenance rules live in [AGENTS.md](AGENTS.md). Commands and API examples live in [docs/minimal-workflow.md](docs/minimal-workflow.md).

## Editing approach

Start with one clip, a source-timestamped transcript, and a plain story cut. Review the story before adding captions and purposeful visuals. Keep the treatment minimal: hard cuts, the better repeated take, real references, and restrained effects.

Keep predictable work deterministic through the tools and shared defaults in `aiedit/presets.py`: typography, caption grouping, speech/quiet detection, cut timing, source-time mapping, entrance sounds, and encoding. The agent handles ambiguous take selection, caption corrections, title wording, reference choice, contextual placement, and exceptions found during review. Preserve approved cuts and text; do not rerun detection merely because defaults changed.

## Local files and revisions

- Start the app with `./start.sh` at `127.0.0.1:8775`. Use `python3 scripts/editor.py` through the same API as the browser.
- Keep source media unchanged. All recognition and media processing stay local. `.aiedit/` holds private media, transcripts, models, working files, exports, and feedback; keep those contents out of Git except its storage README and empty project placeholder. Keep captured evidence, personal paths, and machine-specific capture settings private too.
- Read the latest revision before saving. Preserve manual cuts, restored ranges, and human caption corrections. Reconcile HTTP 409 conflicts; never overwrite another editor's work blindly.
- Source timestamps are seconds on the original clip. Cuts remove intervals. Caption exports map to the edited timeline. Preserve source resolution, framing, native aspect ratio and frame rate unless requested otherwise. The browser's vertical export preserves frame rate; review its crop when the source is wide.
- Preserve HDR appearance. Do not tone-map, brighten, or grade the footage automatically. Native HDR exports use 10-bit HEVC with the source color transfer.
- Do not publish finished videos or add paid/cloud integrations unless requested.

## Story and cuts

Prepare through the API, read the raw transcript and word times, and review every retake group in context. Select the better delivery from actual audio/frames; preserve changed meaning and intentional repetition. Resolve routine choices from evidence without asking the user to choose every cut. Recognition confidence alone does not establish quality.

Use the shared speech-gap defaults instead of retuning ordinary gaps per clip. Amplitude detects silence, not false starts or meaning; breaths can trigger speech activity. Review joins before claiming the cut is good. Be explicit if audio listening is unavailable and distinguish signal/word-time checks from listening. Never invent spoken words.

Read relevant reusable feedback and hook performance before planning the opening and CTA. Hook plans do not authorize invented narration. Keep one-edit notes separate from reusable preferences.

## Titles and captions

Read [the reel-titles skill](skills/reel-titles/SKILL.md) for title wording and generation. Use the approved fixed Geeza Pro Regular size, at most two lines, pure black text, joined rounded opaque white backgrounds, and no title shadow or outline. Rewrite long wording instead of shrinking type. Show the opening title for the standard 2.5 edited seconds. Classify title overlays as titles so they do not receive reference entrance sounds.

Keep captions to 1–3 words, in the spoken language, white with a black outline. Use shared presets without redesigning approved formatting on each clip. Correct recognition errors faithfully and preserve human corrections.

## References and B-roll

Inspect assets' actual content. Label/search B-roll and music by subject, mood, purpose, source, and rights. Do not invent provenance or infer a license from a filename.

For web references, capture the real page with browser tools and retain the exact URL. Use a screenshot for static facts, a browser recording for a web action, and an app recording for an app interaction when capture capability is available. Never call a still a recording.

For app demonstrations, use a simulator on this laptop. Read the target repo's current instructions, respect its owned native lane/profile, and use the configured local capture helper. A specific screen requires an interactive leased session; a fresh launch capture does not demonstrate that screen. Preserve provenance and release the owned lease after related captures. A Simulator does not prove real-device enforcement or purchases.

Placement depends on the video: inspect pointing, gaze, face, captions, and available space. Place an inset near the indicated location and keep the presenter, hand, and captions visible. Do not default to full screen. Keep the same reference continuously visible across speech cuts unless an editorial change calls for otherwise.

## Entrance sound

Use the approved local **Bubble pop** once when a screenshot or B-roll reference first appears, at 35% volume. The editor attaches the configured sound to new references automatically. Keep the sound linked to its reference; its timing follows the reference and current cuts without another manually placed audio overlay. Do not retrigger it at speech cuts or add it to ordinary captions, titles, or decorative graphics. Preserve user-adjusted sound settings and approved older manual effects.

Keep the audio file, selected asset ID, offset, and local default configuration private. Never substitute a different sound if the selected asset is unavailable. Review the exact export for synchronization and balance.

## Review and delivery

Render a plain cut and a final candidate for a new edit. For a correction, preserve the approved version and render the changed candidate. Check the exact encoded file for joins, captions, reference placement/continuity, sound, resolution, and color. An export is an immutable review candidate with its own complete edit snapshot and captions. Feedback identifies the exact export, timeline position, change, and reason. Preserve corrections and approvals with their versions.
