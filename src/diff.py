"""anseropolis.diff — NER/number/timeline structured comparison (claim vs evidence)."""

import json
import re

from src.llm import chat

PROMPT = """你是事實查核助手。比較「聲明」和「證據」，找出不一致的地方。

聲明：{claim}

證據：
{evidence}

請檢查三個面向，回覆 JSON（不要加其他文字）：
{{
  "ner": [{{"claim_says": "...", "evidence_says": "...", "type": "人名/機構/地點"}}],
  "numbers": [{{"claim_says": "...", "evidence_says": "...", "field": "金額/人數/比例/等"}}],
  "timeline": [{{"claim_says": "...", "evidence_says": "...", "issue": "時間錯誤/順序倒置/嫁接"}}],
  "verdict": "match 或 mismatch 或 insufficient",
  "summary": "一句話總結"
}}

如果證據不足以判斷，verdict 填 insufficient。如果完全吻合，三個陣列留空。"""


def diff(claims: list[dict]) -> list[dict]:
    """Compare each claim against its evidence. Enriches claims with 'diff' field."""
    for claim in claims:
        evidence = claim.get("evidence", [])
        if not evidence:
            claim["diff"] = {"ner": [], "numbers": [], "timeline": [], "verdict": "insufficient", "summary": "無證據可比對"}
            continue
        ev_text = "\n".join(f"[{i+1}] {e.get('title','')}: {e.get('snippet','')}" for i, e in enumerate(evidence))
        try:
            raw = chat([{"role": "user", "content": PROMPT.format(claim=claim["text"], evidence=ev_text)}])
        except ConnectionError:
            claim["diff"] = {"ner": [], "numbers": [], "timeline": [], "verdict": "insufficient", "summary": "LLM 不可用"}
            continue
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        try:
            obj = json.loads(raw[raw.index("{"):])
        except (json.JSONDecodeError, ValueError):
            obj = {"ner": [], "numbers": [], "timeline": [], "verdict": "insufficient", "summary": raw[:100]}
        claim["diff"] = obj
    return claims
