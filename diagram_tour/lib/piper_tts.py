"""Piper TTS — generates per-sentence WAVs and joins them with explicit
zero-padded silence between sentences.

We do NOT use Piper's `--sentence-silence` flag because it's broken in
the build at /var/llm/a10d-vision/.venv (it produces clipped/garbage
padding instead of real silence). Each sentence is its own Piper call;
silence is wave-module zero bytes.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

from . import config
from .cache import voice_cache_key, voice_cache_path
from .parse_tour_md import split_sentences
from .types import Stop


def piper_one_shot(text: str, out_path: Path, voice_model: Path) -> None:
    """Generate a WAV for a single sentence/chunk of text. No
    --sentence-silence flag (broken in the bundled Piper build).

    `voice_model` is the path to a Piper .onnx voice model. Use
    voices.resolve_voice() to get this from a name."""
    cmd = [
        config.PIPER_BIN,
        "--model", str(voice_model),
        "--output_file", str(out_path),
        "--length-scale", str(config.LENGTH_SCALE),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.communicate(text.encode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {text[:80]}…")


def concat_wavs_with_pauses(sentence_wavs: list[Path], pause_s: float,
                            out_path: Path) -> float:
    """Concatenate per-sentence WAVs into one, inserting `pause_s` of true
    silence (zero samples) between each. Returns total duration in seconds.

    Assumes all WAVs share the same sample rate, channel count, and
    sample width — Piper output is consistent (22050 Hz, mono, s16le).
    """
    if not sentence_wavs:
        raise ValueError("no input wavs")
    with wave.open(str(sentence_wavs[0]), "rb") as w:
        n_channels = w.getnchannels()
        sample_width = w.getsampwidth()
        framerate = w.getframerate()
    silence_frames = int(pause_s * framerate)
    silence_bytes = b"\x00" * (silence_frames * sample_width * n_channels)

    total_frames = 0
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(n_channels)
        out.setsampwidth(sample_width)
        out.setframerate(framerate)
        for i, p in enumerate(sentence_wavs):
            with wave.open(str(p), "rb") as w:
                frames = w.readframes(w.getnframes())
                out.writeframes(frames)
                total_frames += w.getnframes()
            if i < len(sentence_wavs) - 1:
                out.writeframes(silence_bytes)
                total_frames += silence_frames
    return total_frames / framerate


def tts_stop(stop: Stop, out_path: Path, voice_model: Path,
             voice_name: str | None = None,
             cache_dir: Path | None = None,
             ) -> tuple[float, list[float], int]:
    """TTS a tour stop. Generates one WAV per sentence, joins them with
    SENTENCE_PAUSE_S of zero-padded silence between each.

    When `cache_dir` and `voice_name` are both provided, per-sentence WAVs
    are read from / written to a content-keyed cache, so re-renders skip
    TTS for unchanged sentences. The cache is global across all diagrams
    in the same project — same voice + same sentence = one Piper call,
    forever.

    Returns (total_duration_s, per_sentence_durations_s, n_cache_hits) —
    the per-sentence durations feed the matcher's word-timing estimate;
    the cache-hit count is for status logging.
    """
    sentences = split_sentences(stop.text)
    if not sentences:
        raise RuntimeError(f"stop {stop.n} produced no sentences")

    use_cache = cache_dir is not None and voice_name is not None
    sent_wavs: list[Path] = []
    sent_durations: list[float] = []
    cache_hits = 0

    for i, sent in enumerate(sentences):
        if use_cache:
            key = voice_cache_key(voice_name, config.LENGTH_SCALE, sent)
            sent_wav = voice_cache_path(cache_dir, key)
            sent_wav.parent.mkdir(parents=True, exist_ok=True)
            if sent_wav.exists():
                cache_hits += 1
            else:
                piper_one_shot(sent, sent_wav, voice_model)
        else:
            sent_wav = out_path.parent / f"{out_path.stem}-sent-{i:02d}.wav"
            piper_one_shot(sent, sent_wav, voice_model)

        sent_wavs.append(sent_wav)
        with wave.open(str(sent_wav), "rb") as w:
            sent_durations.append(w.getnframes() / w.getframerate())

    total = concat_wavs_with_pauses(sent_wavs, config.SENTENCE_PAUSE_S, out_path)
    return (total, sent_durations, cache_hits)
