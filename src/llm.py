"""anseropolis.llm — LLM inference with three-tier fallback + auto-unload.

Tier 1: mlx-lm (in-process, Apple Silicon native) — load on demand, unload after
Tier 2: llama-server subprocess (auto start/kill)
Tier 3: external server (localhost:8080)
"""

import atexit
import gc
import json
import os
import shutil
import subprocess
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

from src.config import LLM_URL, LLM_MODEL, LLM_AVAILABLE

# ── State ──
_mlx_model = None
_mlx_tokenizer = None
_llama_proc = None
_backend = None  # "mlx" | "subprocess" | "external" | None
_mlx_available = None  # cached check

MLX_MODEL_ID = os.environ.get("ANSEROPOLIS_MLX_MODEL", "mlx-community/Ministral-8B-Instruct-2412-4bit")
LLAMA_GGUF = os.environ.get("ANSEROPOLIS_GGUF", "")


def _load_mlx():
    global _mlx_model, _mlx_tokenizer, _backend
    from mlx_lm import load
    _mlx_model, _mlx_tokenizer = load(MLX_MODEL_ID)
    _backend = "mlx"


def _unload_mlx():
    """Release mlx model from memory."""
    global _mlx_model, _mlx_tokenizer
    _mlx_model = None
    _mlx_tokenizer = None
    gc.collect()


def _try_mlx_available():
    """Check if mlx-lm is importable (without loading model)."""
    global _mlx_available
    if _mlx_available is not None:
        return _mlx_available
    try:
        import mlx_lm  # noqa: F401
        _mlx_available = True
    except ImportError:
        _mlx_available = False
    return _mlx_available


def _try_subprocess():
    global _llama_proc, _backend
    llama_bin = shutil.which("llama-server")
    if not llama_bin or not LLAMA_GGUF:
        return False
    try:
        _llama_proc = subprocess.Popen(
            [llama_bin, "-m", LLAMA_GGUF, "-ngl", "99", "--port", "8080", "-c", "4096"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        atexit.register(_kill_llama)
        for _ in range(30):
            time.sleep(0.5)
            try:
                urlopen("http://localhost:8080/health", timeout=2)
                _backend = "subprocess"
                return True
            except Exception:
                continue
        _kill_llama()
        return False
    except Exception:
        return False


def _try_external():
    global _backend
    if not LLM_AVAILABLE:
        return False
    try:
        urlopen(LLM_URL.replace("/chat/completions", "/models"), timeout=3)
        _backend = "external"
        return True
    except Exception:
        return False


def _kill_llama():
    global _llama_proc
    if _llama_proc:
        _llama_proc.terminate()
        _llama_proc.wait(timeout=5)
        _llama_proc = None


def _ensure_backend():
    global _backend
    if _backend:
        return
    if _try_mlx_available():
        _backend = "mlx"  # will load on demand
        return
    if _try_external():
        return
    if _try_subprocess():
        return
    raise ConnectionError(
        "無法啟動 LLM。請安裝 mlx-lm (`pip install mlx-lm`) "
        "或啟動 llama-server，或在 Claude Code 中讓 AI 代勞。"
    )


def chat(messages: list, max_tokens: int = 512, tools: list = None) -> dict | str:
    """Call LLM. Returns str if no tools, full response dict if tools provided.
    MLX model is loaded on demand and unloaded after each call to free RAM."""
    _ensure_backend()

    if _backend == "mlx":
        return _chat_mlx(messages, max_tokens)
    else:
        return _chat_http(messages, max_tokens, tools)


def _chat_mlx(messages: list, max_tokens: int) -> str:
    global _mlx_model, _mlx_tokenizer
    # Load on demand
    if _mlx_model is None:
        _load_mlx()
    from mlx_lm import generate
    from mlx_lm.utils import apply_chat_template
    prompt = apply_chat_template(_mlx_tokenizer, messages)
    result = generate(_mlx_model, _mlx_tokenizer, prompt=prompt, max_tokens=max_tokens, verbose=False)
    # Unload after use to free ~5GB RAM
    _unload_mlx()
    return result


def _chat_http(messages: list, max_tokens: int, tools: list = None) -> dict | str:
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode()
    req = Request(LLM_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=120)
    except (URLError, ConnectionRefusedError, OSError) as e:
        raise ConnectionError(f"LLM server unreachable at {LLM_URL}: {e}")
    result = json.loads(resp.read())
    if tools:
        return result
    return result["choices"][0]["message"]["content"].strip()
