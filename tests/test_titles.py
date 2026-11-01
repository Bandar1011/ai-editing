import platform

from PIL import Image, ImageStat

from scripts.title_card import title_card


def test_title_has_pure_black_letters_white_plate_and_fits_vertical_frame(tmp_path):
    output = tmp_path / "title.png"
    title_card(
        ["This video was edited", "using artificial intelligence"],
        output,
        font="Arial" if platform.system() == "Darwin" else "DejaVu Sans",
    )
    with Image.open(output) as image:
        assert image.mode == "RGBA"
        assert 0.6 * 2160 <= image.width <= 0.85 * 2160
        assert image.height <= 3840 * 0.18
        assert image.getpixel((0, 0))[3] == 0
        opaque = image.getchannel("A").point(lambda alpha: 255 if alpha == 255 else 0)
        assert ImageStat.Stat(image.convert("RGB"), mask=opaque).extrema == [(0, 255)] * 3
