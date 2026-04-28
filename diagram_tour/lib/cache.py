"""Per-project cache for the diagram-tour pipeline.

Layout:
  <project_root>/.diagram-tour/
  ├── voice-cache/<hash>.wav    per-sentence Piper output, keyed by
  │                             sha256(voice | length_scale | text).
  │                             Hits make iterative narration tweaks
  │                             5× faster — only changed sentences
  │                             re-TTS, not the whole tour.
  └── (future) repo-state.json  hash of repo structure for staleness
                                detection. Triggers a prompt asking
                                the user whether to regenerate the
                                .dot. Lands when codebase analysis
                                ships in the orchestration layer.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


CACHE_DIR_NAME = ".diagram-tour"


def find_project_root(start: Path) -> Path:
    """Walk up from `start` looking for project markers (.git,
    pyproject.toml, package.json, Cargo.toml). Returns the first
    ancestor that has one; falls back to start.parent if none found.

    This is how the cache binds to a single project — every diagram in
    the same repo shares a cache, so identical narration sentences
    only TTS once across diagrams."""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    markers = (".git", "pyproject.toml", "package.json", "Cargo.toml")
    while cur != cur.parent:
        if any((cur / m).exists() for m in markers):
            return cur
        cur = cur.parent
    return (start.resolve().parent if start.is_file() else start.resolve())


def get_cache_dir(start: Path) -> Path:
    """Return <project_root>/.diagram-tour/. Caller is responsible for
    mkdir on subdirectories as needed."""
    return find_project_root(start) / CACHE_DIR_NAME


def voice_cache_dir(cache_dir: Path) -> Path:
    return cache_dir / "voice-cache"


def voice_cache_key(voice_name: str, length_scale: float, sentence: str) -> str:
    """Stable cache key for a per-sentence Piper output.

    Includes voice (different voices → different audio), length_scale
    (different pacing → different audio), and the verbatim sentence
    text (different words → different audio). 16 hex chars is plenty
    for collision avoidance at the volume we're working with."""
    payload = f"{voice_name}|{length_scale}|{sentence}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def voice_cache_path(cache_dir: Path, key: str) -> Path:
    return voice_cache_dir(cache_dir) / f"{key}.wav"


def is_diagram_cache_fresh(dot_path: Path, hires_png: Path,
                           layout_json: Path) -> bool:
    """True when the rendered hi-res PNG and layout JSON both exist and
    are at least as new as the .dot file. Lets us skip re-rendering
    when the diagram source hasn't changed across runs."""
    if not (hires_png.exists() and layout_json.exists()):
        return False
    dot_mtime = dot_path.stat().st_mtime
    return (hires_png.stat().st_mtime >= dot_mtime
            and layout_json.stat().st_mtime >= dot_mtime)
