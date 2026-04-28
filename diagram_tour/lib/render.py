"""ffmpeg-driven rendering: per-stop static clips with overlay chains,
and concat-demuxer splicing of multiple clips into the final MP4.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config
from .types import OverlayEvent


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_static_clip(audio_path: Path, source_png: Path,
                      crop: tuple[int, int, int, int], audio_dur: float,
                      clip_path: Path,
                      overlay_events: list[OverlayEvent] | None = None) -> None:
    """Render a per-stop video clip: crop the focal region, scale to
    1280×720, hold steady for the narration's duration. Composite a
    chain of overlay PNGs at given time windows.

    Each OverlayEvent contributes one entry to ffmpeg's filter chain
    via the overlay filter with `enable='between(t,start,end)'`.
    """
    x, y, w, h = crop
    base_vf = (
        f"[0:v]crop={w}:{h}:{x}:{y},"
        f"scale={config.VIDEO_W}:{config.VIDEO_H}:force_original_aspect_ratio=decrease,"
        f"pad={config.VIDEO_W}:{config.VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=white,"
        f"setsar=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(config.FPS),
        "-i", str(source_png),
        "-i", str(audio_path),
    ]

    overlay_events = overlay_events or []
    for ev in overlay_events:
        cmd.extend(["-i", str(ev.png_path)])

    if overlay_events:
        chain_parts = [base_vf + "[base]"]
        prev_label = "base"
        for i, ev in enumerate(overlay_events):
            input_idx = 2 + i
            out_label = f"o{i}"
            actual_start = max(0.0, ev.start_s - config.ARROW_LEAD_S)
            end_s = min(audio_dur, actual_start + ev.hold_s)
            chain_parts.append(
                f"[{prev_label}][{input_idx}:v]overlay=0:0:"
                f"enable='between(t,{actual_start:.3f},{end_s:.3f})'[{out_label}]"
            )
            prev_label = out_label
        filter_complex = ";".join(chain_parts)
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[{prev_label}]",
            "-map", "1:a",
        ])
    else:
        cmd.extend(["-vf", base_vf.replace("[0:v]", "", 1)])

    cmd.extend([
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "22050", "-ac", "1",
        "-shortest",
        "-t", f"{audio_dur:.3f}",
        str(clip_path),
    ])
    _run(cmd)


def concat_clips(clip_paths: list[Path], list_file: Path,
                 out_path: Path) -> None:
    """Concatenate clips into the final MP4 using the concat demuxer.

    `list_file` is a path the function will write/overwrite with the
    concat manifest; pass a build-dir path so it stays out of source dirs.
    """
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths))
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    _run(cmd)
