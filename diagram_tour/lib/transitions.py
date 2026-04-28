"""ffmpeg pan transition between two crop regions.

Per-frame PIL crops + scale to a temporary directory, then ffmpeg
encodes the PNG sequence as a 1.5s clip with a silent audio track so
the concat demuxer can splice it between static stop clips.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from . import config


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_transition_clip(base_png: Path,
                          crop_a: tuple[int, int, int, int],
                          crop_b: tuple[int, int, int, int],
                          duration_s: float, clip_path: Path) -> None:
    """Render a transition clip that pans/zooms from crop_a to crop_b
    over duration_s seconds. Uses the unhighlighted base image (no red
    boxes during the pan). Silent — silent audio track added so concat
    works.

    Implementation: pre-compute each frame in PIL (clean and predictable),
    assemble as PNG sequence, then encode with ffmpeg.
    """
    from PIL import Image

    fps = config.FPS
    n_frames = max(2, int(duration_s * fps))
    frame_dir = Path(tempfile.mkdtemp(prefix="transition-"))

    def eased(t: float) -> float:
        # cosine ease-in-out for smoother camera motion than linear
        return 0.5 - 0.5 * math.cos(math.pi * t)

    base = Image.open(base_png)
    ax, ay, aw, ah = crop_a
    bx, by, bw, bh = crop_b

    for i in range(n_frames):
        t = eased(i / (n_frames - 1))
        x = int(ax + (bx - ax) * t)
        y = int(ay + (by - ay) * t)
        w = int(aw + (bw - aw) * t)
        h = int(ah + (bh - ah) * t)
        cropped = base.crop((x, y, x + w, y + h))
        cropped.thumbnail((config.VIDEO_W, config.VIDEO_H), Image.LANCZOS)
        canvas = Image.new("RGB", (config.VIDEO_W, config.VIDEO_H), (255, 255, 255))
        ox = (config.VIDEO_W - cropped.width) // 2
        oy = (config.VIDEO_H - cropped.height) // 2
        canvas.paste(cropped, (ox, oy))
        canvas.save(frame_dir / f"frame-{i:04d}.png")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frame_dir / "frame-%04d.png"),
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=mono:sample_rate=22050",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k", "-ar", "22050", "-ac", "1",
        "-shortest",
        "-t", f"{duration_s:.3f}",
        str(clip_path),
    ]
    _run(cmd)

    for f in frame_dir.iterdir():
        f.unlink()
    frame_dir.rmdir()
