import platform

import pytest
from PIL import Image, ImageChops, ImageStat

from scripts.title_card import title_card


def test_title_has_pure_black_letters_white_plate_and_fits_vertical_frame(tmp_path):
    output = tmp_path / "title.png"
    title_card(
        ["This edit", "More AI tools"],
        output,
        font="Arial" if platform.system() == "Darwin" else "DejaVu Sans",
    )
    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert image.width <= 0.85 * 2160
        assert image.height <= 3840 * 0.18
        assert image.getpixel((0, 0))[3] == 0
        opaque = image.getchannel("A").point(lambda alpha: 255 if alpha == 255 else 0)
        assert ImageStat.Stat(image.convert("RGB"), mask=opaque).extrema == [(0, 255)] * 3


def test_title_font_size_stays_the_same_when_other_words_change(tmp_path):
    sizes = []
    for n, second_line in enumerate(["Uses AI", "More AI tools"]):
        output = tmp_path / f"title-{n}.png"
        title_card(["This edit", second_line], output,
                   font="Arial" if platform.system() == "Darwin" else "DejaVu Sans")
        with Image.open(output) as im:
            first = im.crop((0, 0, im.width, im.height // 2))
            opaque = first.getchannel("A").point(lambda a: 255 if a == 255 else 0)
            dark = first.convert("L").point(lambda v: 255 if v < 80 else 0)
            box = ImageChops.multiply(opaque, dark).getbbox()
            sizes.append((box[2] - box[0], box[3] - box[1]))
    assert sizes[0] == sizes[1], f"The same title words changed size: {sizes}"


def test_title_never_uses_more_than_two_lines(tmp_path):
    with pytest.raises(ValueError, match="two lines"):
        title_card(["First", "Second", "Third"], tmp_path / "title.png")


def test_long_title_requires_shorter_wording_instead_of_smaller_type(tmp_path):
    output = tmp_path / "title.png"
    with pytest.raises(ValueError, match="standard size"):
        title_card(["This title is much too long to fit the standard title card at its fixed size"],
                   output, font="Arial" if platform.system() == "Darwin" else "DejaVu Sans")
    assert not output.exists()


@pytest.mark.parametrize("text", [r"First\NSecond\NThird", r"First\nSecond\nThird", "First\rSecond\rThird"])
def test_two_line_limit_also_covers_escaped_and_non_lf_breaks(tmp_path, text):
    with pytest.raises(ValueError, match="two lines"):
        title_card([text], tmp_path / "title.png",
                   font="Arial" if platform.system() == "Darwin" else "DejaVu Sans", size=100)
