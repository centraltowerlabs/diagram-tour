#!/usr/bin/env bash
#
# diagram-tour skill — installer
#
# What this does:
#   1. Verify system dependencies (graphviz, ffmpeg, python3 ≥ 3.10)
#   2. Create a venv in-place at <skill-dir>/.venv
#   3. Install Python deps (Pillow, PyYAML, piper-tts, pathvalidate)
#   4. Download the default Piper voice model (en_US-lessac-medium)
#   5. Run a smoke test that exercises the full TTS path
#
# Idempotent — re-running is safe. Reuses existing venv and cached
# voice models when present.

set -euo pipefail

# ─── Paths and config ─────────────────────────────────
SKILL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SKILL_DIR/.venv"
VOICES_DIR="${PIPER_VOICES_DIR:-$HOME/.local/share/piper-voices}"
DEFAULT_VOICE="${DIAGRAM_TOUR_VOICE:-en_US-lessac-medium}"

# ─── Pretty output ────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[install]${NC} $1"; }
ok()   { echo -e "${GREEN}[install]${NC} ✓ $1"; }
warn() { echo -e "${YELLOW}[install]${NC} ! $1"; }
err()  { echo -e "${RED}[install]${NC} ✗ $1" >&2; }

# ─── 1. System deps ───────────────────────────────────
log "Checking system dependencies…"
missing=()
for cmd in dot ffmpeg python3 curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done

if [ ${#missing[@]} -ne 0 ]; then
    err "Missing required tools: ${missing[*]}"
    echo
    echo "  Install via your package manager:"
    echo "    macOS:        brew install graphviz ffmpeg python3 curl"
    echo "    Ubuntu/Debian: sudo apt install graphviz ffmpeg python3 python3-venv curl"
    echo "    Fedora:       sudo dnf install graphviz ffmpeg python3 curl"
    echo
    exit 1
fi
ok "system deps present (dot, ffmpeg, python3, curl)"

# Need Python 3.10+ for our type-hint syntax
py_major=$(python3 -c 'import sys; print(sys.version_info.major)')
py_minor=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
    err "Python 3.10+ required (found $py_major.$py_minor)"
    exit 1
fi
ok "Python $py_major.$py_minor"

# ─── 2. Venv ──────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    log "Creating venv at $VENV_DIR…"
    python3 -m venv "$VENV_DIR"
    ok "venv created"
else
    log "venv already exists at $VENV_DIR (reusing)"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ─── 3. Python deps ───────────────────────────────────
log "Installing diagram-tour package + deps into venv…"
pip install --upgrade pip --quiet
# Editable install: makes `python -m diagram_tour` and the `diagram-tour`
# console script work from any cwd. Resolves Pillow, PyYAML, piper-tts,
# and pathvalidate from pyproject.toml.
pip install --quiet --editable "$SKILL_DIR"
ok "package installed (editable)"

# Verify the piper binary landed where we expect
PIPER_BIN="$VENV_DIR/bin/piper"
if [ ! -x "$PIPER_BIN" ]; then
    err "piper binary not found at $PIPER_BIN after install"
    err "  pip-installed piper-tts but the executable is missing — check pip output"
    exit 1
fi
ok "piper binary at $PIPER_BIN"

# ─── 4. Default voice model ───────────────────────────
mkdir -p "$VOICES_DIR"
voice_model="$VOICES_DIR/$DEFAULT_VOICE.onnx"
voice_config="$VOICES_DIR/$DEFAULT_VOICE.onnx.json"

if [ -f "$voice_model" ] && [ -f "$voice_config" ]; then
    log "default voice already cached at $VOICES_DIR (reusing)"
else
    # URL pattern: <lang>/<lang_full>/<speaker>/<quality>/<name>
    # For en_US-lessac-medium → en/en_US/lessac/medium/en_US-lessac-medium
    lang_full=$(echo "$DEFAULT_VOICE" | cut -d- -f1)
    speaker=$(echo "$DEFAULT_VOICE" | cut -d- -f2)
    quality=$(echo "$DEFAULT_VOICE" | cut -d- -f3)
    lang_short="${lang_full%%_*}"
    base="https://huggingface.co/rhasspy/piper-voices/resolve/main/$lang_short/$lang_full/$speaker/$quality/$DEFAULT_VOICE"

    log "Downloading default voice ($DEFAULT_VOICE)…"
    if ! curl -fL --progress-bar -o "$voice_model" "$base.onnx"; then
        err "voice model download failed (HTTP error or network issue)"
        rm -f "$voice_model"
        exit 1
    fi
    if ! curl -fL --progress-bar -o "$voice_config" "$base.onnx.json"; then
        err "voice config download failed"
        rm -f "$voice_config"
        exit 1
    fi
    ok "voice model + config downloaded to $VOICES_DIR"
fi

# ─── 5. Smoke test ────────────────────────────────────
log "Running smoke test (Piper TTS)…"
test_wav=$(mktemp -t piper-test-XXXXXX.wav)
trap 'rm -f "$test_wav"' EXIT

# A short test sentence; not the cached one Piper might already have.
echo "Diagram tour installation successful." | \
    "$PIPER_BIN" \
        --model "$voice_model" \
        --output_file "$test_wav" \
        >/dev/null 2>&1

if [ ! -s "$test_wav" ]; then
    err "smoke test failed — Piper produced no output WAV"
    err "  Try running piper manually with --debug to see what's wrong:"
    err "  echo 'test' | $PIPER_BIN --model $voice_model --output_file /tmp/x.wav --debug"
    exit 1
fi
ok "smoke test passed (Piper produced $(du -h "$test_wav" | cut -f1) WAV)"

# ─── 6. Done ──────────────────────────────────────────
echo
ok "Installation complete."
echo
echo "  Skill location:    $SKILL_DIR"
echo "  Python venv:       $VENV_DIR"
echo "  Voice model dir:   $VOICES_DIR"
echo "  Default voice:     $DEFAULT_VOICE"
echo
echo "  Quick start in Claude Code:"
echo "    /diagram-tour explain this codebase"
echo
echo "  Or invoke directly:"
echo "    $VENV_DIR/bin/diagram-tour --dot path/to/diagram.dot"
echo "    $VENV_DIR/bin/python -m diagram_tour --dot path/to/diagram.dot"
echo
echo "  Swap voices via:"
echo "    --voice <name>    (CLI flag, per-invocation)"
echo "    DIAGRAM_TOUR_VOICE=<name>    (env var, per-shell)"
echo "  See https://rhasspy.github.io/piper-samples/ for available voices."
