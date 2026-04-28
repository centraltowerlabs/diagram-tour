"""Piper voice resolution + auto-download.

Resolution priority (high → low):
  1. CLI flag (--voice <name>)
  2. DIAGRAM_TOUR_VOICE env var
  3. Default (DEFAULT_VOICE_NAME)

Voice names follow Piper's convention: <lang_full>-<speaker>-<quality>
e.g. "en_US-lessac-medium", "en_US-ryan-high", "en_GB-alba-medium".
Models are auto-downloaded from rhasspy/piper-voices on Hugging Face
to ~/.local/share/piper-voices/ on first use.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.request import urlretrieve


DEFAULT_VOICE_NAME = "en_US-lessac-medium"
VOICES_DIR = Path.home() / ".local" / "share" / "piper-voices"
ENV_VAR = "DIAGRAM_TOUR_VOICE"

_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def get_voice_name(cli_arg: str | None = None) -> str:
    """Resolve the voice name from the layered config sources."""
    if cli_arg:
        return cli_arg
    return os.environ.get(ENV_VAR, DEFAULT_VOICE_NAME)


def voice_paths(name: str) -> tuple[Path, Path]:
    """Local (model_path, config_path) for a voice (may not exist yet)."""
    return (VOICES_DIR / f"{name}.onnx",
            VOICES_DIR / f"{name}.onnx.json")


def voice_urls(name: str) -> tuple[str, str]:
    """Hugging Face (model_url, config_url) for a voice.

    `name` must be in the form lang_full-speaker-quality, e.g.
    "en_US-ryan-high". Speakers may contain underscores ("jenny_dioco");
    splitting on "-" still yields exactly 3 parts.
    """
    parts = name.split("-")
    if len(parts) != 3:
        raise ValueError(
            f"voice name must be <lang>-<speaker>-<quality>, got: {name!r}")
    lang_full, speaker, quality = parts
    lang_short = lang_full.split("_")[0]
    base = f"{_HF_BASE}/{lang_short}/{lang_full}/{speaker}/{quality}/{name}"
    return (f"{base}.onnx", f"{base}.onnx.json")


def _progress_reporter(file_label: str):
    """Build a urlretrieve reporthook that prints percentage to stderr."""
    def reporthook(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = min(100, done * 100 // total_size)
        mb_done = done / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        sys.stderr.write(
            f"\r  ↓ {file_label}  {pct:>3}%  ({mb_done:5.1f} / {mb_total:5.1f} MB)")
        sys.stderr.flush()
    return reporthook


def download_voice(name: str) -> Path:
    """Download a Piper voice's .onnx + .onnx.json into VOICES_DIR if not
    already cached. Returns the model path."""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    model_path, config_path = voice_paths(name)
    if model_path.exists() and config_path.exists():
        return model_path

    print(f"[voice] {name} not cached; downloading from rhasspy/piper-voices")
    try:
        model_url, config_url = voice_urls(name)
    except ValueError as e:
        sys.exit(f"[voice] error: {e}")

    try:
        urlretrieve(model_url, model_path,
                    reporthook=_progress_reporter(f"{name}.onnx"))
        sys.stderr.write("\n")
        urlretrieve(config_url, config_path,
                    reporthook=_progress_reporter(f"{name}.onnx.json"))
        sys.stderr.write("\n")
    except Exception as e:
        # Clean up partial files so a retry doesn't think they're complete
        for p in (model_path, config_path):
            if p.exists():
                p.unlink()
        sys.exit(f"[voice] download failed: {e}\n"
                 f"        Check your network and that {name!r} exists at\n"
                 f"        https://huggingface.co/rhasspy/piper-voices")

    return model_path


def resolve_voice(cli_arg: str | None = None) -> Path:
    """Top-level entry point: name from CLI/env/default, download if needed,
    return the local .onnx path."""
    name = get_voice_name(cli_arg)
    return download_voice(name)


def list_installed_voices() -> list[str]:
    """Names of voices already downloaded to VOICES_DIR (model + config
    both present)."""
    if not VOICES_DIR.exists():
        return []
    out: list[str] = []
    for model in sorted(VOICES_DIR.glob("*.onnx")):
        if (model.with_suffix(".onnx.json")).exists():
            out.append(model.stem)
    return out
