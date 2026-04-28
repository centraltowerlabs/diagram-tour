"""Tour markdown parsing.

The narration markdown has YAML frontmatter declaring the stop→cluster
mapping, followed by `## Stop N — Title` sections. See CONVENTIONS.md
for the public-facing spec.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import Stop


# ─────────────────────────────────────────────────────────
# Frontmatter
# ─────────────────────────────────────────────────────────


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter at the top of a markdown file.

    Returns (frontmatter_dict, body_text). If no frontmatter is found,
    returns ({}, text).
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        end = text.find("\n---", 4)
        if end == -1:
            return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, text
    return fm, body


def load_stop_to_cluster(tour_md_path: Path) -> dict[int, str | list[str]]:
    """Read the stop→cluster mapping from the tour markdown's frontmatter.

    Frontmatter format:
      ---
      stops:
        1: FULL
        2: cluster_engine
        3: [cluster_apis, cluster_queues]
      ---

    Raises ValueError if the frontmatter is missing or doesn't include a
    stops mapping. Per CONVENTIONS.md, frontmatter is required for v1.
    """
    fm, _ = parse_frontmatter(tour_md_path.read_text())
    fm_stops = (fm or {}).get("stops")
    if not fm_stops:
        raise ValueError(
            f"{tour_md_path} is missing required `stops` frontmatter. "
            f"See CONVENTIONS.md for the spec."
        )
    out: dict[int, str | list[str]] = {}
    if isinstance(fm_stops, dict):
        for k, v in fm_stops.items():
            out[int(k)] = v
    elif isinstance(fm_stops, list):
        for entry in fm_stops:
            out[int(entry["id"])] = entry["cluster"]
    else:
        raise ValueError(
            f"{tour_md_path}: `stops` must be a dict or list of "
            f"{{id, cluster}} entries"
        )
    return out


# ─────────────────────────────────────────────────────────
# Body parsing
# ─────────────────────────────────────────────────────────


def strip_markdown(text: str) -> str:
    """Remove markdown formatting that shouldn't be read aloud.

    Critically: bolds and italics may span newlines in our source markdown
    (paragraphs are wrapped). We use re.DOTALL so the regex matches across
    newlines. Without this, **multi\\nline** bolds leave their asterisks
    in the text and Piper reads them aloud as "asterisk asterisk".
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences. Pause behavior depends on this
    being accurate — split on common terminators followed by whitespace."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_stops(tour_md_path: Path) -> list[Stop]:
    """Extract `## Stop N — Title\\n<body>` sections from the tour
    markdown. Frontmatter is stripped first."""
    text = tour_md_path.read_text()
    _fm, body = parse_frontmatter(text)
    pattern = re.compile(
        r"^## Stop (\d+) — (.+?)$\n(.*?)(?=^## |^---$|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    stops: list[Stop] = []
    for m in pattern.finditer(body):
        n = int(m.group(1))
        title = m.group(2).strip()
        s_body = strip_markdown(m.group(3).strip())
        stops.append(Stop(n=n, title=title, text=s_body))
    stops.sort(key=lambda s: s.n)
    return stops
