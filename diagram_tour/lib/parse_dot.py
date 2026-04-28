"""DOT/Graphviz layout extraction.

Workflow:
  - Render the .dot once with `dot -Tpng -Gdpi=N` to a hi-res PNG
  - Render the .dot once with `dot -Tjson` to extract layout coordinates
  - Parse the JSON to get cluster bboxes and node positions in pixel
    space (after flipping Y from graphviz's bottom-origin convention)
"""
from __future__ import annotations

import json
from pathlib import Path

from .types import Node


# ─────────────────────────────────────────────────────────
# Coordinate conversion
# ─────────────────────────────────────────────────────────


def graphviz_to_image(bbox: tuple[float, float, float, float],
                      gv_w: float, gv_h: float,
                      img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """Convert a graphviz bbox (x_lo, y_lo, x_hi, y_hi, bottom-left origin)
    to an image rect (x, y, w, h, top-left origin)."""
    x_lo, y_lo, x_hi, y_hi = bbox
    sx = img_w / gv_w
    sy = img_h / gv_h
    return (
        int(x_lo * sx),
        int((gv_h - y_hi) * sy),
        int((x_hi - x_lo) * sx),
        int((y_hi - y_lo) * sy),
    )


def union_bbox(bboxes: list[tuple[float, ...]]) -> tuple[float, ...]:
    """Bounding box that contains all the input bboxes (graphviz coords)."""
    return (
        min(b[0] for b in bboxes), min(b[1] for b in bboxes),
        max(b[2] for b in bboxes), max(b[3] for b in bboxes),
    )


# ─────────────────────────────────────────────────────────
# Cluster + node extraction from layout JSON
# ─────────────────────────────────────────────────────────


def get_cluster_bboxes(layout: dict) -> dict[str, tuple[float, ...]]:
    """All cluster bounding boxes from the layout, plus a 'FULL' entry for
    the whole graph. Coordinates are in graphviz units; convert with
    graphviz_to_image() to get pixel-space rects."""
    bboxes: dict[str, tuple[float, ...]] = {}
    for obj in layout.get("objects", []):
        name = obj.get("name", "")
        if not name.startswith("cluster_"):
            continue
        bb = obj.get("bb")
        if bb:
            bboxes[name] = tuple(float(x) for x in bb.split(","))
    gbb = layout.get("bb")
    if gbb:
        bboxes["FULL"] = tuple(float(x) for x in gbb.split(","))
    return bboxes


def get_cluster_label(layout: dict, cluster_name: str) -> str | None:
    """Look up a cluster's label text from the layout."""
    for sg in layout.get("objects", []):
        if sg.get("name") == cluster_name:
            return sg.get("label", "").replace("\\n", " ").strip()
    return None


def get_nodes(layout: dict, gv_w: float, gv_h: float,
              img_w: int, img_h: int) -> list[Node]:
    """Extract individual node positions, labels, and bounding boxes from
    the dot -Tjson layout.

    match_phrases includes every line of each multi-line label, plus the
    bare filename for any line that looks like a directory path (contains
    both '/' and '.'). This lets nodes labeled
    'components/triage/extraction-panel.tsx' match either the directory
    prefix or the bare filename in narration.
    """
    sx = img_w / gv_w
    sy = img_h / gv_h
    nodes: list[Node] = []
    for obj in layout.get("objects", []):
        name = obj.get("name", "")
        if not name or name.startswith("cluster_"):
            continue
        if "pos" not in obj or "label" not in obj:
            continue
        gx, gy = (float(p) for p in obj["pos"].split(","))
        px = int(gx * sx)
        py = int((gv_h - gy) * sy)
        # Width and height are in INCHES; graphviz position units are points (1/72 inch)
        gw_in = float(obj.get("width", 1.0))
        gh_in = float(obj.get("height", 0.5))
        bb_w = int(gw_in * 72 * sx)
        bb_h = int(gh_in * 72 * sy)
        bb_x = px - bb_w // 2
        bb_y = py - bb_h // 2
        label = obj["label"].replace("\\n", "\n").replace("\\l", "\n").replace("\\r", "\n")
        lines = [l.strip() for l in label.split("\n") if l.strip()]
        short = lines[0] if lines else name
        phrases = list(lines)
        for l in lines:
            if "/" in l and "." in l:
                phrases.append(l.rsplit("/", 1)[-1])
        nodes.append(Node(id=name, label=label, short_name=short,
                          match_phrases=phrases, pos_px=(px, py),
                          bbox_px=(bb_x, bb_y, bb_w, bb_h)))
    return nodes


def nodes_in_bbox(nodes: list[Node], bbox_px: tuple[int, int, int, int]) -> list[Node]:
    """Return nodes whose center falls inside the given pixel bbox."""
    x, y, w, h = bbox_px
    return [n for n in nodes
            if x <= n.pos_px[0] <= x + w and y <= n.pos_px[1] <= y + h]


# ─────────────────────────────────────────────────────────
# IO helpers
# ─────────────────────────────────────────────────────────


def load_layout(layout_json_path: Path) -> dict:
    """Read and parse the layout JSON file."""
    with layout_json_path.open() as f:
        return json.load(f)
