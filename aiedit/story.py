"""Word-timed captions and evidence-based, reversible retake decisions."""

import math
import re
import unicodedata
import uuid
from difflib import SequenceMatcher

from .timeline import kept_ranges, validate_intervals

INCOMPLETE_ENDINGS = {
    "i",
    "the",
    "a",
    "an",
    "to",
    "with",
    "my",
    "our",
    "and",
    "because",
    "of",
    "can",
    "في",
    "من",
    "مع",
}


def identifier():
    return uuid.uuid4().hex[:10]


def normalize(text):
    return re.sub(
        r"[^\w\s]", "", unicodedata.normalize("NFKC", text).casefold()
    ).strip()


def bound_words(words, duration):
    result = []
    for word in words:
        if word["start"] >= duration:
            raise ValueError(
                "A word was aligned beyond the recording. Review the source transcript before generating an automatic cut."
            )
        left, right = max(0, word["start"]), min(duration, word["end"])
        if right - left < 0.02:
            raise ValueError(
                "A word boundary at the end of the recording is too uncertain. Review its timing before cutting."
            )
        result.append(dict(word, start=left, end=right))
    return result


def aligned_words(raw):
    """Group subword tokens; derive boundaries from DTW alignment centers, not text length."""
    words = []
    for segment in raw.get("transcription", []):
        groups = []
        for token in segment.get("tokens", []):
            text = token["text"]
            if text.startswith("[_") or not text:
                continue
            if not groups or text[0].isspace():
                groups.append({"text": text.strip(), "tokens": [token]})
            else:
                groups[-1]["text"] += text
                groups[-1]["tokens"].append(token)
        groups = [g for g in groups if normalize(g["text"])]
        if not groups:
            continue
        start, end = segment["offsets"]["from"] / 1000, segment["offsets"]["to"] / 1000
        centers = []
        for group in groups:
            lexical = [t for t in group["tokens"] if normalize(t["text"])]
            anchors = [t["t_dtw"] / 100 for t in lexical if t.get("t_dtw", -1) >= 0]
            if not anchors:
                raise ValueError(
                    "Word alignment is unavailable. Use whisper.cpp with DTW support and flash attention disabled."
                )
            centers.append(max(start, min(end, sum(anchors) / len(anchors))))
        if any(b < a for a, b in zip(centers, centers[1:])):
            raise ValueError(
                "Word alignment was not monotonic; regenerate or correct the transcript."
            )
        boundaries = (
            [start] + [(a + b) / 2 for a, b in zip(centers, centers[1:])] + [end]
        )
        for i, group in enumerate(groups):
            left, right = boundaries[i], boundaries[i + 1]
            if right - left < 0.02:
                # Do not fabricate a duration for tokens the aligner cannot distinguish.
                if words and words[-1]["end"] >= left - 0.02:
                    words[-1]["text"] += " " + group["text"]
                    words[-1]["alignment_warning"] = (
                        "Indistinguishable word boundary; review this phrase."
                    )
                    continue
                raise ValueError(
                    "Some word boundaries could not be aligned; review this recording before cutting it automatically."
                )
            probabilities = [
                t.get("p", 0) for t in group["tokens"] if normalize(t["text"])
            ]
            words.append(
                {
                    "id": identifier(),
                    "start": round(left, 3),
                    "end": round(right, 3),
                    "text": group["text"],
                    "confidence": round(
                        sum(probabilities) / max(1, len(probabilities)), 4
                    ),
                }
            )
    return words


def short_captions(words, cuts=None, duration=None, max_words=3):
    if not 1 <= max_words <= 3:
        raise ValueError("Captions must contain 1 to 3 words.")
    ranges = (
        kept_ranges(duration, cuts or []) if duration is not None else [(0, math.inf)]
    )
    cues = []
    for left, right in ranges:
        group = []

        def emit(group=group, left=left, right=right):
            if group:
                cues.append(
                    {
                        "id": identifier(),
                        "start": max(left, group[0]["start"]),
                        "end": min(right, group[-1]["end"]),
                        "text": " ".join(w["text"] for w in group),
                    }
                )
                group.clear()

        for word in words:
            if word["start"] >= right or word["end"] <= left:
                continue
            tokens = word["text"].split()
            if len(tokens) > max_words:
                raise ValueError(
                    "An unresolved word boundary exceeds the requested caption word limit. Correct the transcript first."
                )
            if group and (
                sum(len(w["text"].split()) for w in group) + len(tokens) > max_words
                or word["start"] - group[-1]["end"] > 0.3
                or word["end"] - group[0]["start"] > 2
            ):
                emit()
            group.append(word)
            if re.search(r"[.!?؟。]$", word["text"]):
                emit()
        emit()
    return [c for c in cues if c["end"] - c["start"] >= 0.02]


def split_existing_captions(cues, max_words=3):
    """Preserve authored text. Long imported cues need real word timings, not evenly split guesses."""
    if any(len(c["text"].split()) > max_words for c in cues if c["text"].strip()):
        raise ValueError(
            "Use 1–3 words per caption. Generate word-timed captions or split this imported cue with source times."
        )
    return cues


def utterances(words):
    result, group = [], []
    for word in words:
        if group and word["start"] - group[-1]["end"] > 0.45:
            result.append(group)
            group = []
        group.append(word)
        if re.search(r"[.!?؟。]$", word["text"]):
            result.append(group)
            group = []
    if group:
        result.append(group)
    return result


def retake_candidates(words, audio_quality=None):
    """Only repeated nearby utterances qualify; deliberate repetition stays reviewable."""
    lines = utterances(words)
    results, used = [], set()
    for i, first in enumerate(lines):
        if i in used:
            continue
        a = [normalize(w["text"]) for w in first]
        for j in range(i + 1, min(len(lines), i + 4)):
            second = lines[j]
            if second[0]["start"] - first[-1]["end"] > 20:
                break
            b = [normalize(w["text"]) for w in second]
            similarity = SequenceMatcher(None, a, b, autojunk=False).ratio()
            prefix = (
                len(a) >= 3
                and len(a) < len(b)
                and a == b[: len(a)]
                and (
                    not re.search(r"[.!?؟。]$", first[-1]["text"])
                    or a[-1] in INCOMPLETE_ENDINGS
                )
            )
            exact = a == b and len(a) >= 4
            if not (exact or prefix or min(len(a), len(b)) >= 5 and similarity >= 0.86):
                continue
            takes = []
            for line in (first, second):
                confidence = sum(w.get("confidence", 0.5) for w in line) / len(line)
                quality = (
                    audio_quality(line[0]["start"], line[-1]["end"])
                    if audio_quality
                    else {}
                )
                fillers = sum(
                    normalize(w["text"]) in {"um", "uh", "erm", "hmm"} for w in line
                )
                complete = (
                    bool(re.search(r"[.!?؟。]$", line[-1]["text"]))
                    and normalize(line[-1]["text"]) not in INCOMPLETE_ENDINGS
                )
                score = (
                    confidence
                    + 0.12 * complete
                    - 0.12 * fillers
                    - 0.4 * quality.get("clipped_fraction", 0)
                )
                takes.append(
                    {
                        "start": line[0]["start"],
                        "end": line[-1]["end"],
                        "text": " ".join(w["text"] for w in line),
                        "score": round(score, 4),
                        "evidence": {
                            "recognition_confidence": round(confidence, 3),
                            "complete_sentence": complete,
                            "filler_count": fillers,
                            **quality,
                        },
                    }
                )
            chosen = 1 if prefix else max(range(2), key=lambda k: takes[k]["score"])
            # Equal evidence has no defensible automatic winner.
            decisive = prefix or abs(takes[0]["score"] - takes[1]["score"]) >= 0.04
            automatic = decisive and (exact or prefix) and j == i + 1
            reason = (
                "Complete retry replaces an unfinished matching start."
                if prefix
                else "Compared recognition confidence, sentence completeness, fillers, and clipping."
            )
            results.append(
                {
                    "id": identifier(),
                    "takes": takes,
                    "selected": chosen if decisive else None,
                    "similarity": round(similarity, 3),
                    "automatic": automatic,
                    "reason": reason
                    if decisive
                    else "The evidence is tied. Compare the takes and choose by delivery.",
                    "status": "selected" if automatic else "review",
                }
            )
            used.update((i, j))
            break
    return results


def retake_cuts(candidates):
    cuts = []
    for candidate in candidates:
        if candidate.get("selected") is None or candidate.get("status") != "selected":
            continue
        for i, take in enumerate(candidate["takes"]):
            if i != candidate["selected"]:
                cuts.append(
                    {
                        "id": "take-" + candidate["id"] + "-" + str(i),
                        "start": take["start"],
                        "end": take["end"],
                        "enabled": True,
                        "kind": "retake",
                    }
                )
    return cuts


def preserve_take_decisions(candidates, previous):
    for candidate in candidates:
        for old in previous:
            same_words = [normalize(t["text"]) for t in old["takes"]] == [
                normalize(t["text"]) for t in candidate["takes"]
            ]
            same_ranges = len(old["takes"]) == len(candidate["takes"]) and all(
                abs(a["start"] - b["start"]) < 0.5 and abs(a["end"] - b["end"]) < 0.5
                for a, b in zip(old["takes"], candidate["takes"])
            )
            if not old.get("automatic", True) and same_words and same_ranges:
                candidate.update(
                    {
                        key: old[key]
                        for key in ("id", "selected", "reason", "status", "automatic")
                    }
                )
                break
    return candidates


def speech_gap_cuts(cues, duration, minimum=0.35, padding=0.10):
    """Complement recognized utterances, so background music does not hide pauses."""
    speech = [
        {
            "start": max(0, c["start"] - padding),
            "end": min(duration, c["end"] + padding),
        }
        for c in cues
        if c["text"].strip()
    ]
    if not speech:
        return []
    return [
        {"id": identifier(), "start": a, "end": b, "enabled": True, "kind": "speech"}
        for a, b in kept_ranges(duration, speech)
        if b - a >= minimum
    ]


def activity_gap_cuts(regions, duration, minimum=0.12):
    if not regions:
        raise ValueError("Speech detection returned no regions; keep the existing cut.")
    validate_intervals(regions, duration)
    return [
        {"id": identifier(), "start": a, "end": b, "enabled": True, "kind": "speech"}
        for a, b in kept_ranges(duration, regions)
        if b - a >= minimum
    ]


def filler_cuts(words):
    fillers = {"um", "uh", "erm", "hmm", "مم", "امم"}
    return [
        {
            "id": identifier(),
            "start": line[0]["start"],
            "end": line[-1]["end"],
            "enabled": True,
            "kind": "filler",
        }
        for line in utterances(words)
        if len(line) <= 2 and all(normalize(w["text"]) in fillers for w in line)
    ]
