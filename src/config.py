"""anseropolis.config — centralised, env-driven configuration."""

import os
from pathlib import Path

# Project root: auto-detect from this file's location (src/config.py → project root)
ANSEROPOLIS_ROOT = Path(os.environ.get(
    "ANSEROPOLIS_ROOT",
    str(Path(__file__).resolve().parent.parent),
))

DATA_DIR = Path(os.environ.get("ANSEROPOLIS_DATA", str(ANSEROPOLIS_ROOT / "data")))
OUTPUT_DIR = Path(os.environ.get("ANSEROPOLIS_OUTPUT", str(ANSEROPOLIS_ROOT / "output")))

LLM_URL = os.environ.get("ANSEROPOLIS_LLM_URL", "http://localhost:8080/v1/chat/completions")

# Optional ML model dirs — None means "skip that feature"
CKIP_MODEL_DIR = os.environ.get("ANSEROPOLIS_CKIP_DIR") or None
CKIP_BATCH_PY = os.environ.get("ANSEROPOLIS_CKIP_BATCH_PY") or None  # path to ckip_batch.py

EMBED_MODEL_DIR = os.environ.get("ANSEROPOLIS_EMBED_DIR") or None

LLM_MODEL = os.environ.get("ANSEROPOLIS_LLM_MODEL", "gemma4")
