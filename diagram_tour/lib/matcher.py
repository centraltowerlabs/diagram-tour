"""Match narration words to nodes (per-node arrows) and to clusters
(cluster-level highlights), using estimated word timings derived from
per-sentence WAV durations.

No external alignment (Whisper) is used — accuracy is ~250ms which is
plenty for an arrow that needs to appear "around when this node is
mentioned." Could be upgraded to whisper alignment later for tighter
sync; the model is already cached at ~/.cache/huggingface/hub/.
"""
from __future__ import annotations

import re

from . import config
from .parse_tour_md import split_sentences
from .types import ClusterEvent, Node, Stop


# ─────────────────────────────────────────────────────────
# Word timing estimation
# ─────────────────────────────────────────────────────────


def estimate_word_timings(stop: Stop, sentence_durations_s: list[float],
                          pause_s: float) -> list[tuple[str, float, float]]:
    """Per-word (start, end) timestamps within a stop's full audio.

    Each sentence's duration is split evenly across its words; silences
    between sentences accumulate to keep the cumulative offset accurate.
    Returns (word_lower, start_s, end_s) tuples — words are case-folded
    and stripped of trailing punctuation for matching."""
    sentences = split_sentences(stop.text)
    if len(sentences) != len(sentence_durations_s):
        raise RuntimeError(
            f"sentence count mismatch: {len(sentences)} vs {len(sentence_durations_s)}"
        )

    out: list[tuple[str, float, float]] = []
    cursor_s = 0.0
    for sent_idx, sent in enumerate(sentences):
        sent_dur = sentence_durations_s[sent_idx]
        words = sent.split()
        if not words:
            cursor_s += sent_dur
            continue
        per_word = sent_dur / len(words)
        for w_idx, w in enumerate(words):
            start = cursor_s + w_idx * per_word
            end = cursor_s + (w_idx + 1) * per_word
            out.append((w.lower().strip(".,;:!?()'\""), start, end))
        cursor_s += sent_dur
        if sent_idx < len(sentences) - 1:
            cursor_s += pause_s
    return out


# ─────────────────────────────────────────────────────────
# Phrase normalization for matching
# ─────────────────────────────────────────────────────────


def expand_camel(name: str) -> str:
    """`extractFromMessage` → 'extract from message' (lowercased)."""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return s.lower()


def normalize_for_match(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Used for both
    target phrases and narration windows so they compare apples-to-apples."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ─────────────────────────────────────────────────────────
# Per-node arrow matching
# ─────────────────────────────────────────────────────────


def find_node_mentions(words: list[tuple[str, float, float]],
                       candidates: list[Node]) -> list[tuple[Node, float]]:
    """For each candidate node, find the first time any of its label
    phrases is mentioned in the narration. Returns a list sorted by time.

    Each label line contributes one or more variants (raw, camelCase
    expanded, with extension stripped). Tokens in the narration are
    normalized and matched against variants in window sizes 3, 2, 1.
    First match wins per node — repeated mentions don't fire repeated
    arrows."""
    if not words or not candidates:
        return []

    tokens = [w[0] for w in words]
    starts = [w[1] for w in words]
    norm_tokens = [normalize_for_match(t) for t in tokens]

    target_phrases: list[tuple[Node, str]] = []
    for n in candidates:
        variants: set[str] = set()
        for raw in n.match_phrases:
            variants.add(normalize_for_match(raw))
            variants.add(normalize_for_match(expand_camel(raw)))
        for v in list(variants):
            for ext in (".ts", ".tsx", ".py", ".js"):
                if v.endswith(" " + ext.lstrip(".")):
                    variants.add(v[:-len(ext)].strip())
        for v in variants:
            if v and len(v) >= 4:
                target_phrases.append((n, v))

    seen_node_ids: set[str] = set()
    mentions: list[tuple[Node, float]] = []
    for win in (3, 2, 1):
        for i in range(len(norm_tokens) - win + 1):
            window = " ".join(norm_tokens[i:i + win]).strip()
            window = re.sub(r"\s+", " ", window)
            if not window:
                continue
            for node, phrase in target_phrases:
                if node.id in seen_node_ids:
                    continue
                if window == phrase:
                    mentions.append((node, starts[i]))
                    seen_node_ids.add(node.id)
    mentions.sort(key=lambda m: m[1])
    return mentions


# ─────────────────────────────────────────────────────────
# Cluster matching
# ─────────────────────────────────────────────────────────


def cluster_natural_name(label: str) -> str:
    """Extract the human-readable name of a cluster from its full label,
    dropping path/parenthesized annotations.

    'Server actions  (src/actions/...)' → 'Server actions'
    'Domain library  (src/lib)'         → 'Domain library'
    'Task Queues'                       → 'Task Queues'
    'extractors/'                       → 'extractors'
    """
    text = label
    for sep in ("(", "—", " - ", ":", "/"):
        idx = text.find(sep)
        if idx > 0:
            text = text[:idx]
            break
    return text.strip()


def find_cluster_events_for_stop(stop: Stop, sent_durations: list[float],
                                 cluster_labels: dict[str, str],
                                 cluster_bboxes_px: dict[str, tuple[int, int, int, int]],
                                 ) -> list[ClusterEvent]:
    """Find when each cluster is mentioned in the narration.

    Matching uses the cluster's natural name (label text before any
    parenthesized annotation or path separator), normalized. The
    narration must contain the natural name in full — no single-token
    prefix matching, which would create false positives like "next task"
    triggering cluster_queues."""
    word_timings = estimate_word_timings(stop, sent_durations, config.SENTENCE_PAUSE_S)
    if not word_timings:
        return []
    norm_tokens = [normalize_for_match(t) for t in (w[0] for w in word_timings)]
    starts = [w[1] for w in word_timings]

    targets: list[tuple[str, str, int]] = []
    for cname, label in cluster_labels.items():
        if not label:
            continue
        phrase = normalize_for_match(cluster_natural_name(label))
        if not phrase or len(phrase) < 4:
            continue
        targets.append((cname, phrase, len(phrase.split())))

    # Allow each cluster to fire multiple times per stop, but debounce
    # to prevent flicker when the same name appears twice in the same
    # sentence. Tracks last-fire-time per cluster.
    last_fire: dict[str, float] = {}
    events: list[ClusterEvent] = []
    # Iterate by token position (then by win size), so events fire in
    # the order they're spoken — important for the debounce window to
    # use the actual time of mention.
    for i in range(len(norm_tokens)):
        for win in (4, 3, 2, 1):
            if i + win > len(norm_tokens):
                continue
            window = re.sub(r"\s+", " ", " ".join(norm_tokens[i:i + win]).strip())
            if not window:
                continue
            for cname, phrase, n in targets:
                if n != win or window != phrase:
                    continue
                t = starts[i]
                last = last_fire.get(cname, -float("inf"))
                if t - last < config.CLUSTER_HL_DEBOUNCE_S:
                    continue
                bb = cluster_bboxes_px.get(cname)
                if bb is not None:
                    events.append(ClusterEvent(
                        cluster_name=cname,
                        label=cluster_labels[cname],
                        start_s=t,
                        bbox_px=bb,
                    ))
                    last_fire[cname] = t
    events.sort(key=lambda e: e.start_s)
    return events


# ─────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────


def crop_to_clip_transform(crop: tuple[int, int, int, int],
                           video_w: int, video_h: int
                           ) -> tuple[float, float, float]:
    """Compute (scale, pad_x, pad_y) for the crop→clip-frame transform,
    mirroring what ffmpeg does with
    `force_original_aspect_ratio=decrease + pad`.

    The crop is uniformly scaled by `scale` (preserving aspect) until
    one dimension reaches the video frame size; the smaller axis is
    centered with white padding. Returns floats — callers cast to int
    for pixel coordinates.

    For aspect-adjusted crops (non-FULL stops, where expand_to_aspect
    produced a 16:9 rect), pad_x and pad_y are ~0 and the transform
    reduces to a uniform scale. For FULL stops on non-16:9 diagrams,
    the padding offset matters and was previously the source of
    overlay misalignment.
    """
    _cx, _cy, cw, ch = crop
    scale = min(video_w / cw, video_h / ch)
    scaled_w = cw * scale
    scaled_h = ch * scale
    pad_x = (video_w - scaled_w) / 2
    pad_y = (video_h - scaled_h) / 2
    return scale, pad_x, pad_y


def source_to_clip_coords(node_pos_px: tuple[int, int],
                          crop: tuple[int, int, int, int],
                          video_w: int, video_h: int) -> tuple[int, int]:
    """Convert source-pixel coordinates to clip-frame pixels via the
    letterbox-aware transform. Correct on both 16:9 crops (where pad
    is zero) and non-16:9 FULL-stop crops (where pad shifts overlays
    into the actual diagram region instead of the white padding bands)."""
    cx, cy, _cw, _ch = crop
    nx, ny = node_pos_px
    scale, pad_x, pad_y = crop_to_clip_transform(crop, video_w, video_h)
    return (int((nx - cx) * scale + pad_x),
            int((ny - cy) * scale + pad_y))


def node_tip_target(node: Node, crop: tuple[int, int, int, int],
                    video_w: int, video_h: int) -> tuple[int, int]:
    """Where the arrow tip should land for a node — the upper-left corner
    of the node's bounding box (in clip-frame pixels), so the arrow
    points AT the node without obscuring its label."""
    bx, by, _, _ = node.bbox_px
    INSET_PX = 8
    return source_to_clip_coords((bx + INSET_PX, by + INSET_PX), crop,
                                 video_w, video_h)


def expand_to_aspect(rect: tuple[int, int, int, int],
                     aspect: float, img_w: int, img_h: int,
                     pad_pct: float = 0.10) -> tuple[int, int, int, int]:
    """Pad rect by pad_pct on all sides, then expand to target aspect
    ratio, clamped to image bounds. Returns (x, y, w, h)."""
    x, y, w, h = rect
    pad_x, pad_y = int(w * pad_pct), int(h * pad_pct)
    x -= pad_x; y -= pad_y; w += 2 * pad_x; h += 2 * pad_y

    if w / h < aspect:
        new_w = int(h * aspect); x -= (new_w - w) // 2; w = new_w
    else:
        new_h = int(w / aspect); y -= (new_h - h) // 2; h = new_h

    x = max(0, min(x, img_w - 1))
    y = max(0, min(y, img_h - 1))
    w = min(w, img_w - x)
    h = min(h, img_h - y)
    return (x, y, w, h)


def expand_pixel_rect(rect: tuple[int, int, int, int], margin_px: int,
                      img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """Expand a pixel rect by margin_px on each side, clamped to image bounds.

    Correct formula: extend left to x-margin (clamped to 0), extend right
    to x+w+margin (clamped to img_w). Width is the difference. The earlier
    implementation added an extra margin_px term to the width, which made
    cluster outlines (and the padding planner that mimics them) disagree
    by HL_MARGIN_PX every run."""
    x, y, w, h = rect
    x_new = max(0, x - margin_px)
    y_new = max(0, y - margin_px)
    x_right = min(img_w, x + w + margin_px)
    y_bottom = min(img_h, y + h + margin_px)
    return (x_new, y_new, x_right - x_new, y_bottom - y_new)


# ─────────────────────────────────────────────────────────
# Per-stop arrow event resolution
# ─────────────────────────────────────────────────────────


def find_arrow_events_for_stop(
    stop: Stop, crop: tuple[int, int, int, int],
    all_nodes: list[Node], sent_durations: list[float],
    focal_bboxes_px: list[tuple[int, int, int, int]] | None,
    is_full_stop: bool, video_w: int, video_h: int,
) -> list[tuple[Node, float, tuple[int, int]]]:
    """Per-node arrow events for one stop. Returns no per-node arrows on
    FULL stops — those use cluster-level highlights instead."""
    from .parse_dot import nodes_in_bbox
    if is_full_stop:
        return []
    if focal_bboxes_px:
        candidates: list[Node] = []
        for bb in focal_bboxes_px:
            candidates.extend(nodes_in_bbox(all_nodes, bb))
        seen: set[str] = set()
        uniq: list[Node] = []
        for n in candidates:
            if n.id not in seen:
                seen.add(n.id); uniq.append(n)
        candidates = uniq
    else:
        candidates = nodes_in_bbox(all_nodes, crop)
    if not candidates:
        return []
    word_timings = estimate_word_timings(stop, sent_durations, config.SENTENCE_PAUSE_S)
    mentions = find_node_mentions(word_timings, candidates)
    events: list[tuple[Node, float, tuple[int, int]]] = []
    for node, start_s in mentions:
        clip_xy = node_tip_target(node, crop, video_w, video_h)
        if 0 <= clip_xy[0] <= video_w and 0 <= clip_xy[1] <= video_h:
            events.append((node, start_s, clip_xy))
    return events
