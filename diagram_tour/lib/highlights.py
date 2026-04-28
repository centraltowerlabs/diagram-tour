"""PIL overlay rendering: per-node arrows, cluster boxes, and per-stop
highlighted source PNGs (red rectangle drawn around the focal cluster
on the hi-res diagram).
"""
from __future__ import annotations

import math
from pathlib import Path

from . import config
from .matcher import crop_to_clip_transform, expand_pixel_rect, expand_to_aspect
from .types import Node


# ─────────────────────────────────────────────────────────
# Per-node arrow overlay
# ─────────────────────────────────────────────────────────


def draw_arrow_overlay(tip_clip_xy: tuple[int, int]):
    """Render an RGBA overlay (1280×720) with an amber arrow whose tip
    is at tip_clip_xy, pointing in from the upper-left at 35°. Returns
    a PIL Image."""
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (config.VIDEO_W, config.VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    tip_x, tip_y = tip_clip_xy

    angle_rad = math.radians(35)
    L = config.ARROW_LENGTH_PX
    sw = config.ARROW_STEM_W
    hl = config.ARROW_HEAD_LEN
    hw = config.ARROW_HEAD_W

    tail_dx = -math.cos(angle_rad) * L
    tail_dy = -math.sin(angle_rad) * L
    tail_x = tip_x + tail_dx
    tail_y = tip_y + tail_dy

    local_pts = [
        (0, -sw), (0, sw),
        (L - hl, sw), (L - hl, hw),
        (L, 0),
        (L - hl, -hw), (L - hl, -sw),
    ]
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    world_pts = [
        (tail_x + lx * cos_a - ly * sin_a, tail_y + lx * sin_a + ly * cos_a)
        for lx, ly in local_pts
    ]
    draw.polygon(world_pts, fill=config.ARROW_COLOR, outline=config.ARROW_OUTLINE, width=3)
    return overlay


# ─────────────────────────────────────────────────────────
# Cluster box overlay
# ─────────────────────────────────────────────────────────


def cluster_bbox_to_clip(bbox_src: tuple[int, int, int, int],
                         crop: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Convert a source-pixel cluster bbox to clip-frame coordinates,
    accounting for letterbox padding when the crop's aspect ratio
    doesn't match the target video aspect (typical for FULL stops on
    non-16:9 diagrams)."""
    bx, by, bw, bh = bbox_src
    cx, cy, _cw, _ch = crop
    scale, pad_x, pad_y = crop_to_clip_transform(crop, config.VIDEO_W, config.VIDEO_H)
    return (int((bx - cx) * scale + pad_x),
            int((by - cy) * scale + pad_y),
            int(bw * scale),
            int(bh * scale))


def draw_cluster_overlay(cluster_bbox_clip: tuple[int, int, int, int]):
    """Render an RGBA overlay (1280×720) with a yellow rectangle around a
    cluster's bbox in clip-frame coordinates. The rectangle is expanded
    outward by CLUSTER_HL_PADDING_PX so it doesn't sit flush against the
    cluster label or edge nodes. Returns a PIL Image."""
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", (config.VIDEO_W, config.VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x, y, w, h = cluster_bbox_clip
    pad = config.CLUSTER_HL_PADDING_PX
    draw.rectangle([(x - pad, y - pad), (x + w + pad, y + h + pad)],
                   outline=config.CLUSTER_HL_COLOR,
                   width=config.CLUSTER_HL_WIDTH_PX)
    return overlay


# ─────────────────────────────────────────────────────────
# Per-stop highlighted source PNG (red rectangle around focal cluster)
# ─────────────────────────────────────────────────────────


def make_highlighted_source(target: str | list[str], base_img,
                            img_w: int, img_h: int,
                            full_bbox_px: tuple[int, int, int, int],
                            cluster_bboxes_px: dict[str, tuple[int, int, int, int]],
                            out_path: Path) -> tuple[int, int, int, int]:
    """Save a per-stop source PNG with the focal cluster highlighted via
    a red rectangle drawn HL_MARGIN_PX outside the cluster bbox.

    Returns the crop rect (x, y, w, h) in pixels — large enough to fit
    the expanded red rectangle plus visual breathing room, in the right
    aspect ratio for VIDEO_W × VIDEO_H.

    `target` is the focal area: "FULL" for whole image (no highlight),
    a single cluster id, or a list of cluster ids. `full_bbox_px` and
    `cluster_bboxes_px` are pre-computed in padded-image pixel coords
    (caller is responsible for any letterbox padding offset)."""
    from PIL import Image, ImageDraw

    img = base_img.copy()
    draw = ImageDraw.Draw(img)
    expanded_rects: list[tuple[int, int, int, int]] = []

    if target == "FULL":
        crop_seed = full_bbox_px
    else:
        focal_clusters = target if isinstance(target, list) else [target]
        for c in focal_clusters:
            tight = cluster_bboxes_px[c]
            expanded = expand_pixel_rect(tight, config.HL_MARGIN_PX, img_w, img_h)
            ex, ey, ew, eh = expanded
            draw.rounded_rectangle(
                [(ex, ey), (ex + ew, ey + eh)],
                radius=config.HL_CORNER_RADIUS_PX,
                outline=config.HL_COLOR,
                width=config.HL_WIDTH_PX_AT_DPI200,
            )
            expanded_rects.append(expanded)

        if len(expanded_rects) == 1:
            crop_seed = expanded_rects[0]
        else:
            x_lo = min(r[0] for r in expanded_rects)
            y_lo = min(r[1] for r in expanded_rects)
            x_hi = max(r[0] + r[2] for r in expanded_rects)
            y_hi = max(r[1] + r[3] for r in expanded_rects)
            crop_seed = (x_lo, y_lo, x_hi - x_lo, y_hi - y_lo)

    img.save(out_path, optimize=False)

    aspect = config.VIDEO_W / config.VIDEO_H
    return expand_to_aspect(crop_seed, aspect, img_w, img_h, pad_pct=0.10)
