# One-clip workflow

The [resource pack](https://246bfcda.ht-ml.app/) is a menu of 58 references with different levels of demonstrated use. It is not an instruction to install all of them. This project implements the core local editing and review loop first.

1. **Brief and preserve.** Import one source clip, define the audience and point, and record references and asset sources. Keep originals separate from working files and renders.
2. **Index speech.** Generate the full transcript with original timestamps. Correct recognition errors against the audio; keep the spoken language.
3. **Shape the story.** Select source ranges, remove repeated attempts and false starts where appropriate, and preserve meaning. Use silence detection only as supporting evidence.
4. **Hear a plain cut.** Render without burned captions. Check the actual encoded file, especially sentence joins and clipped words.
5. **Add the needed treatment.** Correct and style captions. Define what each screenshot or B-roll overlay explains, and try a short sample before rendering the complete treatment.
6. **Review a specific candidate.** Save feedback with the version, playback time, change, and reason. Link completed corrections to a later export. Explicitly mark preferences that should guide future edits.
7. **Finish the candidate.** Review framing, language, audio, timing, asset sources, and usage rights in the encoded export. Share only when directed.

## Initial tool choices

| Tool | Role here | Status |
| --- | --- | --- |
| [FFmpeg](https://ffmpeg.org/) | Proxies, waveforms, silence evidence, cuts, caption rendering, encoded exports | Implemented and exercised on generated media |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Local multilingual transcription | Implemented; needs a compatible local model |
| Python, FastAPI, plain browser JavaScript | Revision-checked agent/browser workflow, versions, review notes | Implemented |
| [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) | Alternative Apple Silicon transcription route from the pack | Not needed alongside the installed whisper.cpp engine |
| [Remotion](https://github.com/remotion-dev/remotion) | Optional authored motion/composition | Deferred until a clip needs it |
| [Robust Video Matting](https://github.com/PeterL1n/RobustVideoMatting) | Optional presenter extraction | Deferred until a clip needs it |
| [George Showroom](https://github.com/georgewangyu/george-showroom) | Review-workflow reference | This app implements its own versioned review; no integration is claimed |

No untested shelf tool is represented as an installed or validated production dependency. Check upstream setup and licensing before adopting optional tools.

## Review memory

Export manifests freeze cut intervals, captions and style, source ranges, asset references, brief, and output checksum. Feedback points to a particular export filename and edited playback time. The history API searches saved changes and reasons. `reusable=true` filters for explicitly reusable feedback; it does not silently turn one-off requests into defaults.

Generated transcripts remain available separately from edited captions. If a human changes captions while transcription runs, the operation preserves the human changes and reports a conflict; the generated transcript remains in the working folder.

## Implemented minimal workflow

See [minimal-workflow.md](minimal-workflow.md) for word-timed short captions, speech-gap cuts, retake decisions, hook/CTA planning, local asset and music organization, real web references, same-laptop app capture, overlays, punch-ins, and music mixing. The active engine is whisper.cpp DTW; WhisperX remains a documented alternative rather than an installed dependency.
