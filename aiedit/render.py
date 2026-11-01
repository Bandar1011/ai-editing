"""FFmpeg composition with source-time overlays, restrained punch-ins, and ducked music."""

import uuid

from .timeline import ass_text, kept_ranges, remap_subtitles


def mapped_spans(start, end, kept):
    offset = 0
    result = []
    for left, right in kept:
        a, b = max(start, left), min(end, right)
        if b - a >= 0.02:
            result.append(
                {
                    "start": offset + a - left,
                    "end": offset + b - left,
                    "source_start": a,
                }
            )
        offset += right - left
    return result


def export_video(project, source, output_dir, burn_subtitles, assets=None, plain=False):
    from . import media

    assets = assets or {}
    kept = kept_ranges(project["media"]["duration"], project["cuts"])
    if not kept:
        raise ValueError("There is no video left to export. Restore a cut first.")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{uuid.uuid4().hex[:10]}.mp4"
    audio = project["media"]["has_audio"]
    width, height = (
        project["media"]["width"] // 2 * 2,
        project["media"]["height"] // 2 * 2,
    )
    total = sum(b - a for a, b in kept)
    filters, concat = [], []
    inputs = ["-i", str(source.resolve())]
    for i, (start, end) in enumerate(kept):
        filters.append(
            f"[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{i}]"
        )
        concat.append(f"[v{i}]")
        if audio:
            tail = max(0, end - start - 0.012)
            filters.append(
                f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,afade=t=out:st={tail:.6f}:d=0.012[a{i}]"
            )
            concat.append(f"[a{i}]")
    filters.append(
        "".join(concat)
        + f"concat=n={len(kept)}:v=1:a={int(audio)}[vcat]"
        + ("[voice]" if audio else "")
    )
    filters.append(f"[vcat]scale={width}:{height},setsar=1[base]")
    current, count = "base", 0
    if not plain:
        for punch in project.get("punches", []):
            if not punch.get("enabled", True) or punch["scale"] <= 1:
                continue
            spans = mapped_spans(punch["start"], punch["end"], kept)
            if not spans:
                continue
            count += 1
            z = punch["scale"]
            enable = "+".join(
                f"between(t,{s['start']:.6f},{s['end']:.6f})" for s in spans
            )
            filters.extend(
                [
                    f"[{current}]split=2[zb{count}][zc{count}]",
                    f"[zc{count}]crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2,scale={width}:{height}[zoom{count}]",
                    f"[zb{count}][zoom{count}]overlay=0:0:enable='{enable}'[p{count}]",
                ]
            )
            current = f"p{count}"
        input_index = 1
        for overlay in project.get("overlays", []):
            if not overlay.get("enabled", True):
                continue
            asset = assets[overlay["asset_id"]]
            spans = mapped_spans(overlay["start"], overlay["end"], kept)
            for span in spans:
                count += 1
                kind = asset["metadata"]["kind"]
                seek = (
                    overlay.get("asset_in", 0) + span["source_start"] - overlay["start"]
                )
                if kind == "image":
                    inputs += ["-loop", "1", "-framerate", str(project["media"]["fps"])]
                else:
                    inputs += ["-ss", f"{seek:.6f}"]
                inputs += ["-i", str(asset["path"].resolve())]
                layout = overlay.get("layout", "top")
                box_w = (
                    width if layout == "full" else max(2, int(width * 0.88) // 2 * 2)
                )
                box_h = (
                    height if layout == "full" else max(2, int(height * 0.38) // 2 * 2)
                )
                x = (width - box_w) // 2
                y = (
                    0
                    if layout == "full"
                    else int(height * 0.05)
                    if layout == "top"
                    else int(height * 0.48)
                )
                length = span["end"] - span["start"]
                filters.append(
                    f"[{input_index}:v:0]trim=duration={length:.6f},setpts=PTS-STARTPTS+{span['start']:.6f}/TB,scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=0x101312,setsar=1[asset{count}]"
                )
                filters.append(
                    f"[{current}][asset{count}]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0:enable='gte(t,{span['start']:.6f})*lt(t,{span['end']:.6f})'[o{count}]"
                )
                current = f"o{count}"
                input_index += 1
        music = project.get("music")
        if music and music.get("enabled", True):
            asset = assets[music["asset_id"]]
            inputs += ["-stream_loop", "-1", "-i", str(asset["path"].resolve())]
            offset = music.get("offset", 0)
            filters.append(
                f"[{input_index}:a:0]atrim=start={offset}:duration={total:.6f},asetpts=PTS-STARTPTS,volume={music['volume']},afade=t=in:d=0.3,afade=t=out:st={max(0, total - 0.4):.6f}:d=0.4[music]"
            )
            if audio:
                if music.get("duck", True):
                    filters.extend(
                        [
                            "[voice]asplit=2[dry][control]",
                            "[music][control]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=250[ducked]",
                            "[dry][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[mixed]",
                        ]
                    )
                else:
                    filters.append(
                        "[voice][music]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[mixed]"
                    )
            else:
                filters.append("[music]anull[mixed]")
            audio_label = "mixed"
        else:
            audio_label = "voice" if audio else None
    else:
        audio_label = "voice" if audio else None
    cues = remap_subtitles(project["subtitles"], kept)
    if burn_subtitles and not plain and cues:
        caption_path = output.with_suffix(".ass")
        caption_path.write_text(
            ass_text(cues, width, height, project["subtitle_style"]), encoding="utf-8"
        )
        filters.append(f"[{current}]ass=filename={caption_path.name}[vout]")
    else:
        filters.append(f"[{current}]null[vout]")
    command = [
        media.binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        *inputs,
        "-filter_complex_threads",
        "2",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
    ]
    if audio_label:
        command += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k"]
    command += [
        "-t",
        f"{total:.6f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(project["media"]["fps"]),
        "-fps_mode",
        "cfr",
        "-threads",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ]
    media.run(command, cwd=output_dir, timeout=14400)
    media.probe(output)
    return output
