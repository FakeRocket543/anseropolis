"""anseropolis.llm — shared LLM chat interface."""

import json
from urllib.request import urlopen, Request

from src.config import LLM_URL, LLM_MODEL


def chat(messages: list, max_tokens: int = 512, tools: list = None) -> dict | str:
    """Call LLM via OpenAI-compatible API.
    
    Returns str (content) if no tools, full response dict if tools provided.
    """
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
    resp = urlopen(req, timeout=120)
    result = json.loads(resp.read())
    if tools:
        return result
    return result["choices"][0]["message"]["content"].strip()
