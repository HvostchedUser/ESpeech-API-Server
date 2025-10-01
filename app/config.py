# app/config.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any


# ---- Paths ----
BASE_DIR: Path = Path(__file__).resolve().parents[1]
VOICES_DIR: Path = Path(os.environ.get("ESPEECH_VOICES_DIR", BASE_DIR / "voices"))
OUTPUT_DIR: Path = Path(os.environ.get("ESPEECH_OUTPUT_DIR", BASE_DIR / "outputs"))
STATIC_DIR: Path = BASE_DIR / "static"

# Ensure output dir exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Model settings ----
MODEL_CFG: Dict[str, Any] = {
    "dim": int(os.environ.get("ESPEECH_MODEL_DIM", 1024)),
    "depth": int(os.environ.get("ESPEECH_MODEL_DEPTH", 22)),
    "heads": int(os.environ.get("ESPEECH_MODEL_HEADS", 16)),
    "ff_mult": int(os.environ.get("ESPEECH_MODEL_FF_MULT", 2)),
    "text_dim": int(os.environ.get("ESPEECH_MODEL_TEXT_DIM", 512)),
    "conv_layers": int(os.environ.get("ESPEECH_MODEL_CONV_LAYERS", 4)),
}

MODEL_REPO: str = os.environ.get("ESPEECH_MODEL_REPO", "ESpeech/ESpeech-TTS-1_SFT-256K")
MODEL_FILE: str = os.environ.get("ESPEECH_MODEL_FILE", "espeech_tts_256k.pt")
VOCAB_FILE: str = os.environ.get("ESPEECH_VOCAB_FILE", "vocab.txt")

# ---- Vocoder (Vocos) settings ----
# We still call the upstream load_vocoder(), but we can prefetch this repo into the HF cache
# so it doesn't attempt a network request each time.
VOCODER_REPO: str = os.environ.get("ESPEECH_VOCODER_REPO", "charactr/vocos-mel-24khz")

# If true, snapshot the vocoder repo into the HF cache at startup (default: on)
VOCODER_PREFETCH: bool = os.environ.get("ESPEECH_VOCODER_PREFETCH", "1") != "0"

# If true, set HF_HUB_OFFLINE=1 *after* prefetch (skip network checks later)
VOCODER_OFFLINE_AFTER_PREFETCH: bool = os.environ.get("ESPEECH_VOCODER_OFFLINE", "0") == "1"

# ---- Inference defaults ----
DEFAULT_NFE_STEP: int = int(os.environ.get("ESPEECH_DEFAULT_NFE_STEP", 64))
DEFAULT_SPEED: float = float(os.environ.get("ESPEECH_DEFAULT_SPEED", 1.0))
DEFAULT_SEED: int = int(os.environ.get("ESPEECH_DEFAULT_SEED", -1))  # -1 = random

# Limit concurrent synth jobs. GPU typically likes very low concurrency.
MAX_WORKERS: int = int(os.environ.get("ESPEECH_MAX_WORKERS", 1))

# If True, keep model/vocoder resident on the selected device between jobs.
KEEP_MODEL_IN_MEMORY: bool = os.environ.get("ESPEECH_KEEP_MODEL", "1") != "0"

# Allowed reference audio extensions
AUDIO_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".m4a")

# API base prefix (used by the front-end when building URLs)
API_BASE: str = os.environ.get("ESPEECH_API_BASE", "/api")

# ---- Output cleanup policy ----
# Delete generated files that haven't been accessed for this many seconds.
# Default: 1 hour.
OUTPUT_RETENTION_SECONDS: int = int(os.environ.get("ESPEECH_OUTPUT_RETENTION_SECONDS", 3600))

# How often to sweep for expired outputs (seconds). Default: 5 minutes.
CLEANUP_INTERVAL_SECONDS: int = int(os.environ.get("ESPEECH_CLEANUP_INTERVAL_SECONDS", 300))
