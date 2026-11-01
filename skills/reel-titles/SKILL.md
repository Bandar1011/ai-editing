---
name: reel-titles
description: Write and style opening titles for Bandar's Reels Factory videos using the spoken content, his Arabic voice, verified TikTok examples, and their observed view counts. Use for choosing or revising a reel's title and its white background; not for transcribing captions or unrelated copywriting.
---

# Reel titles

Read [the title patterns](references/title-patterns.md) before choosing a title. Keep the video’s actual promise and Bandar’s conversational Arabic. A title may paraphrase the video; it must not invent a result, tutorial, price, time saving, guarantee, or spoken line.

Read the current transcript, clip context, authored corrections, and reusable title feedback. Identify the useful outcome, intended viewer, and evidence the video actually supplies. Draft a few different hooks privately, then choose the shortest clear one that earns its promise. Explain the choice briefly when presenting an edit. Avoid making the video about its editing tool unless that is the point of the clip.

Prefer a specific outcome or question over generic labels. A personal result needs first-person evidence; a how-to title needs an actual method or usable resource. A curiosity gap should reveal its subject and payoff. Keep natural Saudi wording, familiar product names, and Arabic punctuation. Do not turn a punchy title into vague hype. The 1–3-word limit applies to subtitles, not the opening title. Aim for one idea across one or two lines, usually about 4–10 words, with sensible phrase breaks. Rewrite excessive text before making it tiny.

When researching examples, read the on-screen title, not only the post description. Compare both recent/lower-view and higher-view examples from the same profile and topic. Record each exact post URL, observed view count, date, and title separately from interpretation. Profile-grid crops are not reliable for measuring 9:16 geometry; inspect original 9:16 frames or origin covers too. A reply bubble, document heading, or post without a title is not a sample of the standard title template. View totals are associations, affected by topic, age, distribution, delivery, and audience; do not call a title proven or claim it caused those views. Label new explanations as hypotheses. Let the user's later analysis refine the reasoning.

For Reels Factory, render Geeza Pro Regular for Arabic with pure black letters on an opaque, pure white background. Join the rounded backgrounds across lines, matching each line's width. Use no shadow, outline, texture, opacity fade, or faux bold on the title. Keep short titles visibly large: target roughly 70–80% of frame width, allowing variation with word length. Avoid covering the face; use the real frame to choose the top position. Keep a 2–3-second edited-time duration (normally 2.5 seconds).

Generate a transparent card using `uv run scripts/title_card.py PRIVATE_OUTPUT --line "..." --line "..."`. Its fitting controls target width and limit card height to 18% of a 9:16 frame. This is a starting point, not a substitute for inspecting the actual video. Use the card's actual dimensions for normalized overlay width/height; never stretch it into a preset box. Import through the running editor API, save against the latest revision, and preserve other edits.

For HLG title overlays, set `white_nits: 1000` so the plate reaches clean frame white instead of the 203-nit reference-graphics gray. Leave the footage's color, exposure, and framing untouched. Ordinary reference assets retain their 203-nit default. PQ also supports the title setting but player tone mapping differs; inspect the encoded result. Keep HDR composition in 4:4:4 10-bit until encoding, preserving alpha. Check both title lines, lower edges, black/white interiors, disappearance time, and unaffected footage in the exact export. Do not claim a font's identity from pixels alone or promise identical appearance on every display.

Store downloaded examples, counts, covers, transcripts, comparisons, and user media privately outside Git. The project can cache a research summary under `.aiedit/title-research/`. Commit only the reusable rules and code. This skill does not authorize posting a video, contacting anyone, or adding an external model service.
