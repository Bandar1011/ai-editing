# Browser editing workflow

Open Reels Factory at `http://127.0.0.1:8775` with `./start.sh`. The connected assistant needs access to this laptop's browser/local tools. The website does not embed an LLM, use a model API key or upload footage for processing.

## One repeated flow

1. Import the video. The app copies the original into private storage, builds a browser proxy and prepares its waveform. The video becomes playable before waveform generation finishes.
2. Press Prepare video. It can queue behind the initial preview, so neither the user nor the assistant needs to wait and resubmit. One native worker protects the laptop's memory. The UI reports queued work, the actual stage and elapsed processing time.
3. The app prepares source audio, word-timed recognition, speech/quiet evidence, retake candidates and short captions. Recordings with no audio or only digital silence keep their interaction flow without recognition or automatic cuts. It reuses complete analysis when its source, model, tool runtime and settings match. A retry keeps valid completed stages. It applies the resulting edit once, preserving manual/restored footage and reviewed takes. An identical preparation leaves later human corrections intact.
4. The assistant reads source-time context, resolves ambiguous take choices first, then handles faithful subtitle fixes, title wording and purposeful B-roll. A small guarded editorial action applies only those decisions, using the same models and normalization rules as browser edits. It does not make the assistant assemble a complete project snapshot. Detection, grouping, standard type, timing, reference pop and encoding remain code responsibilities. Existing style/profile analysis is reused.
5. Review in the live browser preview. Caption or placement changes do not require a new render. Export when ready or when a particular encoded candidate is needed. Identical rendered content reuses verified bytes but receives a new independent review snapshot and captions.

A context response covers up to 60 source seconds and returns `window.next_start`. It separates original words from editable captions, includes take evidence and existing cuts, and flags low-confidence words for inspection. Confidence alone cannot establish a better delivery. Asset results retain source/rights metadata; flags indicate when a bounded collection has more results. Read the full project or search the asset library when those details are needed.

`GET /api/projects/ID/status` omits old export snapshots. `GET /api/projects/ID/context?start=0` supplies editorial context. `PATCH /api/projects/ID/editorial` accepts `base_revision` and targeted `caption_fixes`, `take_choices`, overlay upserts and story fields. It preserves untouched text, layout and assets. It applies the whole batch atomically or returns an error. Take choices precede caption/visual decisions because they can change caption IDs. Existing project saves require `base_revision`; take decisions also accept it and reject stale versions. CLI examples live in [minimal-workflow.md](minimal-workflow.md). `prepare ID --wait` waits for its specific job and returns the first context window.

## Reliability and speed

The cache contains source facts and encoded derivatives, never a project snapshot to replay over human work. Dependency changes invalidate affected facts. Incomplete or corrupt artifacts are recomputed. A failed preparation does not apply half an edit. Restart marks queued/running work interrupted; an explicit retry resumes valid facts. The app retains previous exports and source media.

Recognition and media duration still determine first-time processing cost. Queue delay and desktop load also vary. Stage records distinguish processing from waiting and record reuse, so a slower operation has an inspectable cause. This is a repeatable execution path, not a promise of identical wall-clock time for every video.

Export reuse is conservative. Source/assets, effective edits, renderer/tool/encoder settings and installed caption font resources affect its identity. Loaded libraries, the OS runtime and active font configuration are accounted for. Unknown loader/font configuration disables reuse. Font inventory metadata includes inode and change time so replacing an installed face also invalidates reuse. A label, review note or project revision does not change encoded content. Reused bytes are checksum-verified and copied, with separate immutable MP4, SRT and JSON records. The encoder, HDR treatment and output cadence are unchanged.

## Research behind the choices

- [Descript's Underlord primer](https://www.descript.com/blog/article/underlord-ai-video-editor-primer) describes an assistant working through transcripts and editor tools. We use the same division between editorial judgment and execution, with the local assistant connection instead of embedding a provider.
- [OpusClip's editing guide](https://www.opus.pro/blog/claude-video-editing-tutorial) describes structured editing scripts shared with its web editor, asynchronous rendering and explicit export. We keep one browser/API edit representation, expose job state and review interactively before export. Its public guide does not disclose its internal performance architecture.
- [Auto-Editor's cache documentation](https://auto-editor.com/docs/subcommands/cache) documents reuse of audio and motion analysis. We cache our existing local speech and quiet analysis rather than replacing the detector or retuning approved cuts.
- [OpenCut Classic](https://github.com/OpenCut-app/opencut-classic) demonstrates a local browser editor approach, but that repository is archived and the [current project](https://github.com/OpenCut-app/OpenCut) is a rewrite. A migration would add work without resolving our specific repeated-analysis and coordination problems.

These sources inform the design. Their marketing speed claims are not measurements of Reels Factory. Local measurements use generated media and the production workflow; personal footage stays out of CI.
