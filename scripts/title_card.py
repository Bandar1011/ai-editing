# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=11"]
# ///
"""Create a transparent title with joined, rounded white line backgrounds.

Run with uv; FFmpeg/libass shapes Arabic locally using an installed font.
"""

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aiedit import media


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


def title_card(lines, output, width=2160, font="Geeza Pro", weight=400, size=196):
    if not lines or any(not line.strip() for line in lines):
        raise ValueError("Each title line must contain text.")
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
                f"PlayResX:{width * 2}\nPlayResY:{size * 3}\nWrapStyle:2\n"
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
                f"color=black@0:s={width * 2}x{size * 3},format=rgba",
                "-vf", "ass=title.ass:alpha=1", "-frames:v", "1", "-threads", "1", str(image),
            ], cwd=root, check=True, capture_output=True)
            with Image.open(image) as source:
                bounds = source.getchannel("A").getbbox()
                if bounds is None:
                    raise ValueError("The selected font did not render the title.")
                if bounds[0] <= 1 or bounds[2] >= source.width - 1:
                    raise ValueError("Title line exceeds the render canvas. Shorten it or lower --size.")
                rendered.append(source.crop(bounds))
        padding = round(size * 0.37)
        available = round(width * 0.84) - 2 * padding
        shrink = min(1, available / max(im.width for im in rendered))
        if shrink < 1:
            rendered = [im.resize((round(im.width * shrink), round(im.height * shrink)), Image.Resampling.LANCZOS) for im in rendered]
        row_height = max(im.height for im in rendered) + round(size * 0.48)
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
        contour = rounded_polygon(points, size * 0.2)
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
    parser.add_argument("--size", type=int, default=196)
    parser.add_argument("--font", default="Geeza Pro")
    parser.add_argument("--weight", type=int, default=400)
    args = parser.parse_args()
    print(title_card(args.line, args.output.resolve(), args.width, args.font, args.weight, args.size))
