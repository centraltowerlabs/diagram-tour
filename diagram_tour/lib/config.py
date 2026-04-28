"""Static pipeline configuration constants. Per-run paths live on the
RunConfig in render_video.py; this file is for values that don't change
across runs of the same diagram-tour version."""
from __future__ import annotations

from pathlib import Path

# ─── External tools ─────────────────────────────────────
# PIPER_BIN is environment-specific and will move to the install.sh / env
# discovery layer when the package becomes a public skill. The voice model
# is now resolved at runtime via lib/voices.py (CLI flag → env var →
# default) with auto-download from rhasspy/piper-voices.
PIPER_BIN = "/var/llm/a10d-vision/.venv/bin/piper"

# ─── Video / render parameters ──────────────────────────
VIDEO_W, VIDEO_H = 1280, 720
DPI = 200
FPS = 30
LENGTH_SCALE = 1.05      # piper speaking rate (>1.0 = slower)
# NOTE: Piper's --sentence-silence flag is buggy in the build at
# /var/llm/a10d-vision/.venv (it produces clipped/garbage padding instead
# of real silence). We sentence-split the text in Python, call Piper
# per-sentence, and concatenate WAVs with explicit zero-padded silence.
SENTENCE_PAUSE_S = 0.40

# ─── Red focal-cluster outline ──────────────────────────
HL_COLOR = (220, 38, 38, 255)   # tailwind red-600
HL_WIDTH_PX_AT_DPI200 = 32      # rectangle border thickness at 200 DPI
HL_MARGIN_PX = 80               # how far OUTSIDE the cluster bbox to draw
HL_CORNER_RADIUS_PX = 48        # rounded-corner radius for the red outline

# ─── Pan transition between stops ───────────────────────
TRANSITION_S = 1.5

# ─── Per-node arrows ────────────────────────────────────
ARROW_COLOR = (251, 191, 36, 255)        # tailwind amber-400
ARROW_OUTLINE = (120, 53, 15, 255)       # tailwind amber-900 (slim outline)
ARROW_LENGTH_PX = 110                    # tip-to-tail in clip-frame pixels
ARROW_STEM_W = 18                        # stem half-width
ARROW_HEAD_LEN = 40                      # arrowhead length (back from tip)
ARROW_HEAD_W = 35                        # arrowhead half-width
ARROW_HOLD_S = 1.4                       # how long each arrow stays on screen
ARROW_LEAD_S = 0.10                      # appear this much before the word

# ─── Cluster-level highlights (yellow box around a cluster) ──
CLUSTER_HL_COLOR = (251, 191, 36, 220)   # amber-400 with slight transparency
CLUSTER_HL_WIDTH_PX = 8                  # in clip-frame px
CLUSTER_HL_PADDING_PX = 12               # in clip-frame px; breathing room around the cluster bbox
                                          # so the box doesn't sit flush against cluster labels
# Multiple mentions of the same cluster within a stop will each fire a
# separate yellow-box highlight, but only if they're at least this far
# apart in the audio. Prevents repeated mentions in the same sentence
# from creating a flicker; allows the user to reinforce a cluster
# across paragraphs.
CLUSTER_HL_DEBOUNCE_S = 3.0
