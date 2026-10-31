"""Source-time edits and their output-time subtitle mappings."""

import math
import re
import uuid


def kept_ranges(duration: float, cuts: list[dict]) -> list[tuple[float, float]]:
    removed = sorted(
        (max(0.0, float(c["start"])), min(duration, float(c["end"])))
        for c in cuts
        if c.get("enabled", True)
    )
    merged: list[list[float]] = []
    for start, end in removed:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 0.001:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    kept = []
    cursor = 0.0
    for start, end in merged:
        if start - cursor > 0.01:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor > 0.01:
        kept.append((cursor, duration))
    return kept


def remap_subtitles(
    subtitles: list[dict], kept: list[tuple[float, float]]
) -> list[dict]:
    result = []
    offset = 0.0
    for start, end in kept:
        for cue in sorted(subtitles, key=lambda c: c["start"]):
            left, right = max(start, cue["start"]), min(end, cue["end"])
            if right - left < 0.02 or not cue["text"].strip():
                continue
            mapped = {
                "start": offset + left - start,
                "end": offset + right - start,
                "text": cue["text"],
            }
            if (
                result
                and result[-1]["text"] == mapped["text"]
                and abs(result[-1]["end"] - mapped["start"]) < 0.025
            ):
                result[-1]["end"] = mapped["end"]
            else:
                result.append(mapped)
        offset += end - start
    return sorted(result, key=lambda c: c["start"])


def timestamp(seconds: float, ass: bool = False) -> str:
    scale = 100 if ass else 1000
    units = max(0, round(seconds * scale))
    hours, rest = divmod(units, 3600 * scale)
    minutes, rest = divmod(rest, 60 * scale)
    secs, fraction = divmod(rest, scale)
    return (
        f"{hours}:{minutes:02}:{secs:02}.{fraction:02}"
        if ass
        else f"{hours:02}:{minutes:02}:{secs:02},{fraction:03}"
    )


def srt_text(cues: list[dict]) -> str:
    return (
        "\n\n".join(
            f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text'].strip()}"
            for i, c in enumerate(cues, 1)
        )
        + "\n"
    )


def parse_srt(content: str) -> list[dict]:
    pattern = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    cues = []
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip()):
        match = pattern.search(block)
        if not match:
            continue
        values = list(map(int, match.groups()))

        def seconds(v):
            return v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000

        text = block[match.end() :].strip()
        if text:
            cues.append(
                {
                    "id": uuid.uuid4().hex[:10],
                    "start": seconds(values[:4]),
                    "end": seconds(values[4:]),
                    "text": text,
                }
            )
    return cues


def validate_intervals(items: list[dict], duration: float) -> None:
    for item in items:
        start, end = item["start"], item["end"]
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end > duration + 0.05
            or end - start < 0.02
        ):
            raise ValueError(
                "Each range must stay inside the video and last at least 0.02 seconds."
            )


def ass_text(cues: list[dict], width: int, height: int, style: dict) -> str:
    size = round(style["font_size"] * height / 1080, 2)
    margin = round(height * 0.065)
    alignment = 8 if style["position"] == "top" else 2
    outline = max(1, round(height / 540, 2))
    result = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},0,{alignment},{margin},{margin},{margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        text = (
            cue["text"]
            .replace("\\", "\\\\")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace("\r", "")
            .replace("\n", "\\N")
        )
        result.append(
            f"Dialogue: 0,{timestamp(cue['start'], True)},{timestamp(cue['end'], True)},Default,,0,0,0,,{text}"
        )
    return "\n".join(result) + "\n"
