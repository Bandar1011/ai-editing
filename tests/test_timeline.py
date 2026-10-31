import pytest

from aiedit.timeline import (
    kept_ranges,
    parse_srt,
    remap_subtitles,
    srt_text,
    validate_intervals,
)


def test_overlapping_and_disabled_cuts_do_not_remove_time_twice():
    cuts = [
        {"start": 1, "end": 3},
        {"start": 2, "end": 4},
        {"start": 6, "end": 9, "enabled": False},
        {"start": 8, "end": 10},
    ]
    assert kept_ranges(10, cuts) == [(0, 1), (4, 8)]


def test_subtitles_crossing_a_cut_join_on_output_timeline():
    kept = [(0, 2), (4, 7)]
    cues = [
        {"start": 1, "end": 5, "text": "Keep this sentence"},
        {"start": 2.1, "end": 3.9, "text": "Cut this"},
        {"start": 6, "end": 7, "text": "End"},
    ]
    assert remap_subtitles(cues, kept) == [
        {"start": 1, "end": 3, "text": "Keep this sentence"},
        {"start": 4, "end": 5, "text": "End"},
    ]


def test_unicode_multiline_srt_round_trip():
    cues = parse_srt("1\r\n00:00:01,120 --> 00:00:03,050\r\nمرحبًا\r\nWelcome\r\n")
    assert cues[0]["text"] == "مرحبًا\nWelcome"
    assert "00:00:01,120 --> 00:00:03,050" in srt_text(cues)


@pytest.mark.parametrize(
    "start,end", [(float("nan"), 1), (0, float("inf")), (-1, 2), (2, 1), (0, 11)]
)
def test_invalid_ranges_cannot_be_saved(start, end):
    with pytest.raises(ValueError):
        validate_intervals([{"start": start, "end": end}], 10)
