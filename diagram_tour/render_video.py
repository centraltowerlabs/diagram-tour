"""Main entry point: turn a .dot diagram + a tour markdown into a
narrated MP4. See CONVENTIONS.md for the expected markdown spec.

Usage:
    python -m diagram_tour --dot path/to/diagram.dot
    python -m diagram_tour --dot path/to/diagram.dot --tour path/to/tour.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .lib import config
from .lib.cache import (
    get_cache_dir,
    is_diagram_cache_fresh,
    voice_cache_dir,
)
from .lib.highlights import (
    cluster_bbox_to_clip,
    draw_arrow_overlay,
    draw_cluster_overlay,
    make_highlighted_source,
)
from .lib.matcher import (
    find_arrow_events_for_stop,
    find_cluster_events_for_stop,
)
from .lib.parse_dot import (
    get_cluster_bboxes,
    get_cluster_label,
    get_nodes,
    graphviz_to_image,
    load_layout,
)
from .lib.parse_tour_md import (
    load_stop_to_cluster,
    parse_stops,
)
from .lib.piper_tts import tts_stop
from .lib.render import build_static_clip, concat_clips
from .lib.transitions import build_transition_clip
from .lib.types import OverlayEvent
from .lib.voices import DEFAULT_VOICE_NAME, ENV_VAR as VOICE_ENV_VAR
from .lib.voices import get_voice_name, resolve_voice


@dataclass
class RunPaths:
    """Per-run filesystem layout. Derived from the --dot argument's path
    + stem. Intermediate build artifacts live inside the per-project
    .diagram-tour/ cache; outputs sit next to the .dot."""
    dot: Path
    tour_md: Path
    layout_json: Path
    hires_raw_png: Path         # raw graphviz output (not 16:9-padded)
    hires_png: Path             # padded to 16:9, used downstream
    build_dir: Path
    tour_output_dir: Path
    latest_symlink: Path
    cache_dir: Path             # <project_root>/.diagram-tour/


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a narrated diagram tour video from a .dot "
                    "file and a markdown narration script.")
    p.add_argument("--dot", type=Path, required=True,
                   help="Path to the .dot file")
    p.add_argument("--tour", type=Path, default=None,
                   help="Path to the tour markdown (default: derived from --dot)")
    p.add_argument("--voice", type=str, default=None,
                   help=(f"Piper voice name (e.g. en_US-ryan-high). "
                         f"Auto-downloaded from rhasspy/piper-voices if not "
                         f"cached. Falls back to ${VOICE_ENV_VAR} env var, "
                         f"then to {DEFAULT_VOICE_NAME}."))
    return p.parse_args(argv)


def resolve_paths(args: argparse.Namespace) -> RunPaths:
    """Build a RunPaths from CLI args."""
    dot = args.dot.resolve()
    dot_dir = dot.parent
    stem = dot.stem
    cache_dir = get_cache_dir(dot)
    return RunPaths(
        dot=dot,
        tour_md=(args.tour.resolve() if args.tour
                 else dot_dir / f"{stem}-tour.md"),
        layout_json=dot_dir / f"{stem}.layout.json",
        hires_raw_png=dot_dir / f"{stem}-hires-raw.png",
        hires_png=dot_dir / f"{stem}-hires.png",
        build_dir=cache_dir / f"build-{stem}",
        tour_output_dir=dot_dir / f"{stem}-renders",
        latest_symlink=dot_dir / f"{stem}-tour-latest.mp4",
        cache_dir=cache_dir,
    )


def compute_safe_padding(cluster_bboxes_raw: dict[str, tuple[int, int, int, int]],
                         src_w: int, src_h: int,
                         target_aspect: float,
                         hl_margin_px: int,
                         pad_pct: float = 0.10
                         ) -> tuple[int, int, int, int, int, int]:
    """Compute (left, right, top, bottom, final_w, final_h) padding such
    that every cluster's 16:9-expanded focal crop fits within the padded
    image without clamping.

    Mimics the math expand_to_aspect uses on each cluster: outer margin,
    pad_pct expansion, then aspect-fill. Returns the OOB overhangs on
    each side (max across all clusters), then ensures the final canvas
    is itself 16:9 by extending the shorter axis.

    The output padded image satisfies two properties:
      1. Every cluster's focal crop will be exactly 16:9 (no clamping)
      2. The canvas itself is 16:9 (FULL crop fills the frame)
    """
    max_left = 0
    max_right = 0
    max_top = 0
    max_bottom = 0

    for bx, by, bw, bh in cluster_bboxes_raw.values():
        # Outer margin (HL_MARGIN_PX) — same as expand_pixel_rect
        bx -= hl_margin_px; by -= hl_margin_px
        bw += hl_margin_px * 2; bh += hl_margin_px * 2

        # pad_pct expansion (first step of expand_to_aspect)
        pad_x = int(bw * pad_pct)
        pad_y = int(bh * pad_pct)
        bx -= pad_x; by -= pad_y
        bw += pad_x * 2; bh += pad_y * 2

        # Expand to target aspect (centered)
        if bw / bh < target_aspect:
            new_w = int(bh * target_aspect)
            extra = (new_w - bw) // 2
            bx -= extra
            bw = new_w
        else:
            new_h = int(bw / target_aspect)
            extra = (new_h - bh) // 2
            by -= extra
            bh = new_h

        # Track OOB on each side
        if bx < 0:
            max_left = max(max_left, -bx)
        if by < 0:
            max_top = max(max_top, -by)
        if bx + bw > src_w:
            max_right = max(max_right, bx + bw - src_w)
        if by + bh > src_h:
            max_bottom = max(max_bottom, by + bh - src_h)

    # After per-cluster padding, ensure canvas itself is 16:9
    initial_w = src_w + max_left + max_right
    initial_h = src_h + max_top + max_bottom
    if initial_w / initial_h > target_aspect:
        # Wider than 16:9 → extend height
        target_h = int(round(initial_w / target_aspect))
        extra = target_h - initial_h
        max_top += extra // 2
        max_bottom += extra - extra // 2
    elif initial_w / initial_h < target_aspect:
        # Taller than 16:9 → extend width
        target_w = int(round(initial_h * target_aspect))
        extra = target_w - initial_w
        max_left += extra // 2
        max_right += extra - extra // 2

    final_w = src_w + max_left + max_right
    final_h = src_h + max_top + max_bottom
    return max_left, max_right, max_top, max_bottom, final_w, final_h


def render_diagram(paths: RunPaths) -> bool:
    """Render the raw hi-res PNG and layout JSON from .dot if they're stale
    (or missing). Returns True if rendering happened, False if cached
    outputs were reused.

    The raw PNG (paths.hires_raw_png) is the direct graphviz output. The
    padded PNG (paths.hires_png) — which is what every downstream consumer
    uses — is produced separately in main() by pad_to_aspect, which always
    runs (idempotent and cheap) so we can recover original src dims even on
    cache hit."""
    if is_diagram_cache_fresh(paths.dot, paths.hires_raw_png, paths.layout_json):
        return False
    subprocess.run(["dot", f"-Gdpi={config.DPI}", "-Tpng",
                    str(paths.dot), "-o", str(paths.hires_raw_png)], check=True)
    subprocess.run(["dot", "-Tjson",
                    str(paths.dot), "-o", str(paths.layout_json)], check=True)
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_paths(args)

    # ── Dependency / input checks ────────────────────────
    for path, label in [(paths.dot, "diagram .dot"),
                        (paths.tour_md, "tour markdown")]:
        if not path.exists():
            sys.exit(f"missing {label}: {path}")
    for tool in ("dot", "ffmpeg", config.PIPER_BIN):
        if shutil.which(tool) is None and not Path(tool).exists():
            sys.exit(f"{tool} is not on PATH")

    # ── Resolve voice (CLI → env → default), download if missing ──
    voice_name = get_voice_name(args.voice)
    print(f"[voice] using {voice_name}")
    voice_model = resolve_voice(args.voice)

    # ── Output directories ──────────────────────────────
    paths.build_dir.mkdir(exist_ok=True)
    paths.tour_output_dir.mkdir(exist_ok=True)
    voice_cache_dir(paths.cache_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_mp4 = paths.tour_output_dir / f"{paths.dot.stem}-tour-{timestamp}.mp4"

    # ── Render hi-res PNG + layout JSON (skip if cache fresh) ───
    rendered = render_diagram(paths)
    if rendered:
        print(f"[1/6] Rendered {paths.hires_png.name} at {config.DPI} DPI")
    else:
        print(f"[1/6] Reused cached {paths.hires_png.name} (.dot unchanged)")

    print(f"[2/6] Loading cluster layout JSON…")
    layout = load_layout(paths.layout_json)

    from PIL import Image
    raw_img = Image.open(paths.hires_raw_png).convert("RGBA")
    src_w, src_h = raw_img.size
    print(f"      Image (rendered): {src_w}x{src_h}")

    # Compute cluster bboxes in raw-image pixel coords so we can size the
    # padding to fit every cluster's 16:9 expansion without clamping.
    bboxes = get_cluster_bboxes(layout)
    full_bb = bboxes["FULL"]
    gv_w = full_bb[2] - full_bb[0]
    gv_h = full_bb[3] - full_bb[1]
    cluster_bboxes_raw: dict[str, tuple[int, int, int, int]] = {}
    for cname, gv_bb in bboxes.items():
        if cname == "FULL":
            continue
        cluster_bboxes_raw[cname] = graphviz_to_image(gv_bb, gv_w, gv_h, src_w, src_h)

    # Cluster-aware source padding. Each cluster's focal crop will go
    # through expand_to_aspect (outer margin → pad_pct → aspect-fill).
    # We compute the worst-case OOB across every cluster and pad the
    # source by exactly that much, plus whatever's needed to make the
    # canvas itself 16:9. Result: every focal crop is exact 16:9 (no
    # clamping → no letterbox), AND the FULL canvas is 16:9 (FULL crop
    # fills the frame).
    target_aspect = config.VIDEO_W / config.VIDEO_H
    left_pad, right_pad, top_pad, bottom_pad, img_w, img_h = compute_safe_padding(
        cluster_bboxes_raw, src_w, src_h, target_aspect,
        hl_margin_px=config.HL_MARGIN_PX, pad_pct=0.10,
    )

    if any((left_pad, right_pad, top_pad, bottom_pad)):
        padded = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
        padded.paste(raw_img, (left_pad, top_pad))
        padded.save(paths.hires_png)
        base_img = padded
        print(f"      Image (padded for cluster fit): {img_w}x{img_h} "
              f"(L={left_pad} R={right_pad} T={top_pad} B={bottom_pad})")
    else:
        if not paths.hires_png.exists() or paths.hires_png.read_bytes() != paths.hires_raw_png.read_bytes():
            paths.hires_png.write_bytes(paths.hires_raw_png.read_bytes())
        base_img = raw_img
        print(f"      Image (no padding needed): {img_w}x{img_h}")

    # ── Parse stops + cluster mapping ───────────────────
    stops = parse_stops(paths.tour_md)
    stop_to_cluster = load_stop_to_cluster(paths.tour_md)
    expected = len(stop_to_cluster)
    if len(stops) != expected:
        sys.exit(f"expected {expected} stops (per stops frontmatter), "
                 f"parsed {len(stops)}")
    print(f"[3/6] Parsed {len(stops)} stops from {paths.tour_md.name}")

    # ── Extract nodes + cluster labels for matching ─────
    # graphviz_to_image and get_nodes use the ORIGINAL (pre-pad) image
    # dimensions because the graph occupies the original area within the
    # padded canvas. We then shift every coordinate by (left_pad, top_pad)
    # so it's correct in the padded coord space everything else uses.
    raw_nodes = get_nodes(layout, gv_w, gv_h, src_w, src_h)
    if left_pad or top_pad:
        from .lib.types import Node
        all_nodes = [
            Node(id=n.id, label=n.label, short_name=n.short_name,
                 match_phrases=n.match_phrases,
                 pos_px=(n.pos_px[0] + left_pad, n.pos_px[1] + top_pad),
                 bbox_px=(n.bbox_px[0] + left_pad, n.bbox_px[1] + top_pad,
                          n.bbox_px[2], n.bbox_px[3]))
            for n in raw_nodes
        ]
    else:
        all_nodes = raw_nodes

    # Reuse cluster_bboxes_raw computed during padding analysis; just shift
    # each by (left_pad, top_pad) to land in padded-image coords.
    cluster_labels: dict[str, str] = {}
    cluster_bboxes_px: dict[str, tuple[int, int, int, int]] = {}
    for cname, (bx, by, bw, bh) in cluster_bboxes_raw.items():
        cluster_labels[cname] = get_cluster_label(layout, cname) or cname
        cluster_bboxes_px[cname] = (bx + left_pad, by + top_pad, bw, bh)
    # FULL crop = the whole padded image (in padded pixel coords)
    full_bbox_px = (0, 0, img_w, img_h)
    print(f"      {len(all_nodes)} nodes for arrow targeting; "
          f"{len(cluster_labels)} clusters for cluster-level highlights")

    # ── Pass 1: per-stop static clips ───────────────────
    stop_crops: list[tuple[int, int, int, int]] = []
    static_clip_paths: list[Path] = []

    for stop in stops:
        target = stop_to_cluster[stop.n]
        is_full_stop = (target == "FULL")

        source_png = paths.build_dir / f"stop-{stop.n:02d}-source.png"
        crop = make_highlighted_source(target, base_img, img_w, img_h,
                                       full_bbox_px, cluster_bboxes_px,
                                       source_png)
        stop_crops.append(crop)

        audio_path = paths.build_dir / f"stop-{stop.n:02d}.wav"
        dur, sent_durs, cache_hits = tts_stop(
            stop, audio_path, voice_model,
            voice_name=voice_name, cache_dir=paths.cache_dir,
        )

        focal_bboxes_px = (None if is_full_stop else
                           [cluster_bboxes_px[c] for c in
                            (target if isinstance(target, list) else [target])])

        arrow_events = find_arrow_events_for_stop(
            stop, crop, all_nodes, sent_durs, focal_bboxes_px,
            is_full_stop=is_full_stop,
            video_w=config.VIDEO_W, video_h=config.VIDEO_H,
        )
        # On non-FULL stops, suppress yellow cluster overlay for the focal
        # cluster — the persistent red box already marks it, so concentric
        # red+yellow on the same region is redundant.
        cluster_events = find_cluster_events_for_stop(
            stop, sent_durs, cluster_labels, cluster_bboxes_px,
        )
        if not is_full_stop:
            focal_set = set(target if isinstance(target, list) else [target])
            cluster_events = [ce for ce in cluster_events
                              if ce.cluster_name not in focal_set]

        # Render overlay PNGs and convert to OverlayEvent list
        overlay_dir = paths.build_dir / f"stop-{stop.n:02d}-overlays"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        overlays: list[OverlayEvent] = []
        for i, (_node, start_s, clip_xy) in enumerate(arrow_events):
            png = overlay_dir / f"arrow-{i:02d}.png"
            draw_arrow_overlay(clip_xy).save(png)
            overlays.append(OverlayEvent(
                start_s=start_s, hold_s=config.ARROW_HOLD_S, png_path=png,
            ))
        for i, ce in enumerate(cluster_events):
            png = overlay_dir / f"cluster-{i:02d}.png"
            draw_cluster_overlay(cluster_bbox_to_clip(ce.bbox_px, crop)).save(png)
            # Cluster boxes hold a bit longer so the eye has time to track.
            overlays.append(OverlayEvent(
                start_s=ce.start_s, hold_s=config.ARROW_HOLD_S + 1.0, png_path=png,
            ))
        overlays.sort(key=lambda e: e.start_s)

        clip_path = paths.build_dir / f"stop-{stop.n:02d}.mp4"
        build_static_clip(audio_path, source_png, crop, dur, clip_path,
                          overlay_events=overlays)
        static_clip_paths.append(clip_path)

        target_str = ",".join(target) if isinstance(target, list) else str(target)
        evs = ([f"→{n.short_name}@{t:.1f}" for n, t, _ in arrow_events[:3]]
               + [f"□{ce.label[:12]}@{ce.start_s:.1f}" for ce in cluster_events[:3]])
        ev_str = (", " + ", ".join(evs)
                  + ("…" if (len(arrow_events) + len(cluster_events)) > 6 else "")
                  ) if evs else ""
        n_sent = len(sent_durs)
        hit_str = f" (cache: {cache_hits}/{n_sent})" if cache_hits else ""
        print(f"[4/6] Stop {stop.n:>2}: {dur:5.1f}s  focus={target_str}  "
              f"({stop.title}){hit_str}{ev_str}")

    # ── Pass 2: transition clips between consecutive stops ──
    print(f"[4/6] Building {len(stops) - 1} transition clips "
          f"({config.TRANSITION_S}s each)…")
    transition_paths: list[Path] = []
    for i in range(len(stops) - 1):
        trans_path = paths.build_dir / f"trans-{i + 1:02d}-{i + 2:02d}.mp4"
        build_transition_clip(paths.hires_png, stop_crops[i], stop_crops[i + 1],
                              config.TRANSITION_S, trans_path)
        transition_paths.append(trans_path)

    # Interleave: static_1, trans_1to2, static_2, trans_2to3, ..., static_N
    all_clips: list[Path] = []
    for i, sc in enumerate(static_clip_paths):
        all_clips.append(sc)
        if i < len(transition_paths):
            all_clips.append(transition_paths[i])

    print(f"[5/6] Concatenating {len(all_clips)} clips → {output_mp4.name}")
    concat_list = paths.build_dir / "concat-list.txt"
    concat_clips(all_clips, concat_list, output_mp4)

    # ── Update the "latest" symlink ─────────────────────
    if paths.latest_symlink.is_symlink() or paths.latest_symlink.exists():
        paths.latest_symlink.unlink()
    paths.latest_symlink.symlink_to(output_mp4.relative_to(paths.latest_symlink.parent))

    total = sum(
        wave.open(str(paths.build_dir / f"stop-{s.n:02d}.wav")).getnframes() /
        wave.open(str(paths.build_dir / f"stop-{s.n:02d}.wav")).getframerate()
        for s in stops
    )
    print(f"[6/6] ✓ Done: {output_mp4} ({total/60:.1f} min)")
    print(f"      latest -> {paths.latest_symlink} -> {output_mp4.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
