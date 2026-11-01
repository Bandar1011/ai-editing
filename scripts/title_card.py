# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=11"]
# ///
"""Create a transparent title with joined, rounded white line backgrounds.

Run with uv; FFmpeg/libass shapes Arabic locally using an installed font.
"""

import argparse
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aiedit import media
from aiedit.presets import TITLE


def rounded_polygon(points, radius):
    result = []
    for i, (x, y) in enumerate(points):
        previous, following = points[i - 1], points[(i + 1) % len(points)]
        lengths = [math.dist((x, y), p) for p in (previous, following)]
        distance = min(radius, *(length / 2 for length in lengths))
        a, b = [
            (x + (p[0] - x) * distance / length, y + (p[1] - y) * distance / length)
            for p, length in zip((previous, following), lengths)
        ]
        for step in range(17):
            t = step / 16
            result.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * x + t * t * b[0],
                           (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * y + t * t * b[1]))
    return result


def title_card(lines, output, width=2160, font=TITLE["font_family"],
               weight=TITLE["font_weight"], size=None, target_width=TITLE["max_width"]):
    if any(re.search(r"\\[Nn]", line) for line in lines):
        raise ValueError("Use actual line breaks; titles allow at most two lines.")
    lines = [part for line in lines for part in (line.splitlines() or [""])]
    if len(lines) > TITLE["max_lines"]:
        raise ValueError("A title must use at most two lines. Shorten the wording.")
    if not lines or any(not line.strip() for line in lines):
        raise ValueError("Each title line must contain text.")
    if width < 180 or not 0.3 <= target_width <= 0.9:
        raise ValueError("Use a frame width >=180 and a maximum width between 0.3 and 0.9.")
    size = size if size is not None else TITLE["font_size_at_1080_width"] * width / 1080
    if not 0 < size <= width or weight not in (400, 700):
        raise ValueError("Use a positive font size within the frame and weight 400 or 700.")
    size = round(size, 2)
    render_height = math.ceil(size * 3 / 2) * 2
    if any(c in font for c in ",\n\r{}\\"):
        raise ValueError("Invalid font family.")
    with tempfile.TemporaryDirectory(prefix="reels-title-") as temporary:
        root = Path(temporary)
        rendered = []
        for number, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            ass = root / "title.ass"
            ass.write_text(
                "[Script Info]\nScriptType: v4.00+\n"
                f"PlayResX:{width * 2}\nPlayResY:{render_height}\nWrapStyle:2\n"
                "[V4+ Styles]\n"
                "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
                f"Style: D,{font},{size},&H00000000,&H00000000,&H00000000,&H00000000,{-1 if weight >= 700 else 0},0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
                "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
                f"Dialogue:0,0:00:00.00,0:00:01.00,D,,0,0,0,,{escaped}\n",
                encoding="utf-8",
            )
            image = root / f"line-{number}.png"
            subprocess.run([
                media.binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                f"color=black@0:s={width * 2}x{render_height},format=rgba",
                "-vf", "ass=title.ass:alpha=1", "-frames:v", "1", "-threads", "1", str(image),
            ], cwd=root, check=True, capture_output=True)
            with Image.open(image) as source:
                bounds = source.getchannel("A").getbbox()
                if bounds is None:
                    raise ValueError("The selected font did not render the title.")
                if bounds[0] <= 1 or bounds[2] >= source.width - 1:
                    raise ValueError("Title is too long at the standard size. Shorten the wording.")
                glyph = Image.new("RGBA", (bounds[2] - bounds[0], bounds[3] - bounds[1]))
                # libass's RGB conversion can lift black to 16. Keep only its
                # shaped alpha mask, then paint the letters with exact black.
                glyph.putalpha(source.getchannel("A").crop(bounds))
                rendered.append(glyph)
        padding = round(TITLE["padding_at_1080_width"] * width / 1080)
        row_height = round(TITLE["row_height_at_1080_width"] * width / 1080)
        if any(im.width + 2 * padding > width * target_width or im.height > row_height for im in rendered):
            raise ValueError("Title is too long at the standard size. Shorten it or use two lines.")
        widths = [im.width + 2 * padding for im in rendered]
        card_width = max(widths)
        # Almost equal rows share an edge, avoiding a tiny decorative step.
        widths = [card_width if card_width - w < size * 0.15 else w for w in widths]
        left = [(card_width - w) / 2 for w in widths]
        right = [(card_width + w) / 2 for w in widths]
        points = [(left[0], 0), (right[0], 0)]
        for i in range(len(lines)):
            points.append((right[i], (i + 1) * row_height))
            if i + 1 < len(lines):
                points.append((right[i + 1], (i + 1) * row_height))
        points.append((left[-1], len(lines) * row_height))
        for i in reversed(range(len(lines))):
            points.append((left[i], i * row_height))
            if i:
                points.append((left[i - 1], i * row_height))
        # Remove duplicate/collinear vertices before rounding the contour.
        points = [p for i, p in enumerate(points) if p != points[i - 1]]
        points = [p for i, p in enumerate(points) if not (
            points[i - 1][0] == p[0] == points[(i + 1) % len(points)][0]
            or points[i - 1][1] == p[1] == points[(i + 1) % len(points)][1]
        )]
        canvas = Image.new("RGBA", (card_width, len(lines) * row_height))
        mask = Image.new("L", (card_width * 2, canvas.height * 2))
        contour = rounded_polygon(points, TITLE["radius_at_1080_width"] * width / 1080)
        ImageDraw.Draw(mask).polygon([(x * 2, y * 2) for x, y in contour], fill=255)
        canvas.paste((255, 255, 255, 255), (0, 0), mask.resize(canvas.size, Image.Resampling.LANCZOS))
        for i, image in enumerate(rendered):
            canvas.alpha_composite(image, ((card_width - image.width) // 2, i * row_height + (row_height - image.height) // 2))
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output)
        return canvas.size


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--line", action="append", required=True)
    parser.add_argument("--width", type=int, default=2160)
    parser.add_argument("--size", type=int, help="Explicit user-requested override; defaults to the approved fixed size.")
    parser.add_argument("--max-width", "--target-width", dest="max_width", type=float, default=TITLE["max_width"])
    parser.add_argument("--font", default=TITLE["font_family"])
    parser.add_argument("--weight", type=int, default=TITLE["font_weight"])
    args = parser.parse_args()
    print(title_card(args.line, args.output.resolve(), args.width, args.font, args.weight, args.size, args.max_width))
