"""anseropolis.llm — shared LLM chat interface."""

import json
from urllib.request import urlopen, Request
from urllib.error import URLError

from src.config import LLM_URL, LLM_MODEL, LLM_AVAILABLE


def chat(messages: list, max_tokens: int = 512, tools: list = None) -> dict | str:
    """Call LLM via OpenAI-compatible API.
    
    Returns str (content) if no tools, full response dict if tools provided.
    Raises ConnectionError if LLM not available.
    """
    if not LLM_AVAILABLE:
        raise ConnectionError("LLM not configured (ANSEROPOLIS_LLM_URL is empty)")
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
