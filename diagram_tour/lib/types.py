"""Shared NamedTuple types used across the pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class Stop(NamedTuple):
    """A single tour stop parsed from the markdown narration."""
    n: int
    title: str
    text: str  # markdown stripped, ready for TTS


class Node(NamedTuple):
    """A diagram node extracted from the dot -Tjson layout."""
    id: str                     # graphviz node id
    label: str                  # full label (may contain \n)
    short_name: str             # first non-empty line of label (for logging)
    match_phrases: list[str]    # all label lines, candidates for matching
    pos_px: tuple[int, int]     # center in source-image pixels
    bbox_px: tuple[int, int, int, int]  # (x, y, w, h) in source-image pixels


class ClusterEvent(NamedTuple):
    """A cluster-level highlight: yellow box around the cluster, displayed
    when its name is mentioned in narration."""
    cluster_name: str
    label: str
    start_s: float
    bbox_px: tuple[int, int, int, int]


class OverlayEvent(NamedTuple):
    """Generic time-windowed overlay applied to a static clip. Used for
    both per-node arrows and cluster-level highlight boxes."""
    start_s: float
    hold_s: float
    png_path: Path
