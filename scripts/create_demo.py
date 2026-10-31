"""Create a local spoken sample with deliberate gaps; no API calls or real footage."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aiedit.media import binary, run

folder = ROOT / ".aiedit" / "demo-source"
folder.mkdir(parents=True, exist_ok=True)
target = folder / "A little less silence.mp4"
if target.exists():
    print(target)
    sys.exit(0)
phrases = [
    "Welcome to AI Editing.",
    "Let's remove the pauses and keep the good parts.",
    "You can adjust every cut and subtitle before you export.",
]
clips = []
for i, phrase in enumerate(phrases):
    aiff = folder / f"phrase-{i}.aiff"
    wav = folder / f"phrase-{i}.wav"
    subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), phrase], check=True)
    run(
        [
            binary("ffmpeg"),
            "-v",
            "error",
            "-y",
            "-i",
            str(aiff),
            "-ar",
            "48000",
            "-ac",
            "1",
            str(wav),
        ]
    )
    clips.append(wav.name)
    if i < len(phrases) - 1:
        silence = folder / f"gap-{i}.wav"
        run(
            [
                binary("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=48000:cl=mono:d={1.1 + i * 0.3}",
                str(silence),
            ]
        )
        clips.append(silence.name)
(folder / "audio.txt").write_text("".join(f"file '{name}'\n" for name in clips))
run(
    [
        binary("ffmpeg"),
        "-v",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        "audio.txt",
        "-c:a",
        "pcm_s16le",
        "voice.wav",
    ],
    cwd=folder,
)
raw = json.loads(
    run(
        [
            binary("ffprobe"),
            "-v",
            "error",
            "-show_format",
            "-of",
            "json",
            str(folder / "voice.wav"),
        ]
    )
)
duration = float(raw["format"]["duration"])
font = "/System/Library/Fonts/Supplemental/Arial.ttf"
filters = [
    "drawbox=x=68:y=64:w=72:h=5:color=0xd4ee9f:t=fill",
    f"drawtext=fontfile='{font}':text='AI EDITING / GENERATED SAMPLE':x=68:y=97:fontsize=19:fontcolor=0xa3b697",
    f"drawtext=fontfile='{font}':text='A little less silence.':x=68:y=272:fontsize=70:fontcolor=0xe9efe3",
    f"drawtext=fontfile='{font}':text='A lot more you.':x=68:y=356:fontsize=70:fontcolor=0xd4ee9f",
    f"drawtext=fontfile='{font}':text='Try the cuts. Edit the words. Make it yours.':x=68:y=488:fontsize=24:fontcolor=0x8eaa81",
    "drawbox=x=1065:y=120:w=18:h=390:color=0x34462c:t=fill",
    "drawbox=x=1101:y=200:w=18:h=310:color=0x5e7a48:t=fill",
    "drawbox=x=1137:y=300:w=18:h=210:color=0xd4ee9f:t=fill",
]
run(
    [
        binary("ffmpeg"),
        "-v",
        "error",
        "-n",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x18241d:s=1280x720:r=30:d={duration}",
        "-i",
        str(folder / "voice.wav"),
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(target),
    ]
)
print(target)
