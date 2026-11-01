# Bandar's title patterns

Profile: https://www.tiktok.com/@bandar_h0

Observed 2026-11-01: a sample of 18 distinct post covers (10 from the Popular view and 8 recent posts), with six original 540×960 origin covers checked for geometry. A separate 36-post recent metadata sample supplies descriptions and counts; descriptions are not assumed to be title text. This is a sample, not an exhaustive profile audit. The private research summary contains exact examples and counts.

## Visual preferences

- Arabic letterforms are a close visual match to Geeza Pro Regular, the user's chosen font. The video pixels do not expose an exact font name. Preserve regular weight; do not substitute a decorative Arabic face.
- Black text, clean opaque white, compact padding, rounded outer corners, and rounded transitions where the line widths change. Two lines are common. No title shadow or black outline.
- The checked native covers vary from approximately 55% to 90% of frame width depending on text length; the approved title is about 70%. The user subsequently requested a standard text size and no more than two lines. The shared preset freezes the approved visual scale at 129 px per 1080 frame width. Card width follows the words; do not enlarge or shrink the type to reach a target width for every title.
- The user's recent posts and higher-view posts share this visual treatment. A visual template alone does not account for view differences.

## Writing patterns and plausible reasons

| Pattern | Why it may help | Required support |
| --- | --- | --- |
| A named platform + an overlooked action + a useful outcome | Recognizable subject and a concrete reason to watch | The action and benefit must appear in the clip |
| How I achieved a result despite a constraint | Personal credibility and relevance to a specific viewer | First-person evidence; no invented career result |
| How to get a result while still in a particular situation | Calls out the intended viewer directly | A method or resource the viewer can actually use |
| A specific price, count, or contrast | Concrete stakes and an easy-to-grasp surprise | The exact number must be stated or shown |
| A short personal story with a specific subject | Creates narrative curiosity | A story with a payoff, not a generic advice clip |
| A direct question about a recognizable problem | Gives the viewer a reason to seek an explanation | The video must answer or meaningfully examine it |

The sample includes high-view career tips and personal stories, plus lower-view posts with similarly clear wording. Very similar job-related titles have markedly different view totals. Treat the reasons above as editorial hypotheses, not causal findings or a fixed viral formula. Avoid transferring a travel-story device mechanically to a software demo.

For a demo whose content proves an AI-assisted edit and points to the usable code, a short demonstration claim can be more faithful than a tutorial promise. Show the result and name the useful subject. Choose the wording from that video's transcript, not from the most-viewed post's wording.

## What the open-source repositories actually provide

[TikTok Sans](https://github.com/tiktok/TikTokSans) publishes font sources and build documentation. Its README explicitly excludes Arabic from TikTok Sans coverage. The inspected repository does not provide TikTok's caption editor, rounded-background renderer, or authoritative title size/padding tokens. Use it for supported Latin text only when needed; do not label a Geeza-rendered Arabic title as TikTok Sans.

[Aiden Johnston's Reel Studio](https://github.com/AidenJohnston/reel-studio-app) supplies a useful composition reference, but its Montserrat-based labels are not the user's Arabic template. Do not inherit its font or fixed size in place of the user's references. Recreate the observed white geometry locally and verify it against native frames.
