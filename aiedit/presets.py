"""Shared, fixed defaults calibrated to the creator's approved reel."""

from types import MappingProxyType

TITLE = MappingProxyType({
    "font_family": "Geeza Pro",
    "font_weight": 400,
    "font_size_at_1080_width": 129,
    "row_height_at_1080_width": 172.5,
    "padding_at_1080_width": 47.5,
    "radius_at_1080_width": 25.75,
    "max_width": 0.84,
    "max_lines": 2,
    "duration": 2.5,
    "white_nits": 1000,
})

CAPTIONS = MappingProxyType({
    "font_family": "Geeza Pro",
    "font_weight": 400,
    "font_size": 52,  # Existing caption units: pixels at 1080 image height.
    "outline": 4.5,
    "margin_percent": 23.5,
    "max_words": 3,
})

SPEECH = MappingProxyType({
    "threshold_db": -35,
    "minimum_pause": 0.12,
    "padding": 0.025,
    "vad_threshold": 0.55,
    "minimum_speech_ms": 80,
    "minimum_silence_ms": 80,
})
