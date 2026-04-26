"""anseropolis.decompose — 聲明拆解：Gemma 4 E4B via llama-server"""

import base64
import json
import re
from src.llm import chat as _chat
from pathlib import Path


SYSTEM_PROMPT = """你是事實查核分析師。你的任務是從文字中找出所有包含具體事實的聲明。
即使文字很短，只要包含可以驗證真偽的具體說法（如數字、事件、人名、政策），就要提取出來。
用JSON陣列回覆：[{"text": "聲明內容", "difficulty": "easy/medium/hard"}]
至少提取1個聲明。如果整段都是意見沒有事實，才回覆 []"""

VISION_SYSTEM = """你是事實查核分析師。分析圖片內容，提取可查核的事實聲明。
用JSON回覆：{"description": "圖片描述", "claims": [{"text": "聲明", "difficulty": "easy/medium/hard"}]}"""



def _parse_json(text: str):
    """Extract JSON from LLM output."""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    for i, c in enumerate(text):
        if c in '[{':
            text = text[i:]
            break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        depth = 0
        for i, c in enumerate(text):
            if c in '[{': depth += 1
            elif c in ']}': depth -= 1
            if depth == 0 and i > 0:
                try:
                    return json.loads(text[:i+1])
                except:
                    pass
        return []


def decompose(text: str, image_path: str = None) -> dict:
    """Extract verifiable claims from text and/or image."""
    result = {"claims": [], "vision": None}

    # Text claims (with retry)
    if text:
        # Strip common forwarding prefixes that confuse LLM
        clean = re.sub(r'^(快轉[！!]?\s*|轉傳[！!]?\s*|不轉不是[^\s]*\s*)', '', text)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"提取以下文字的可查核聲明：\n\n{clean}"},
        ]
        for attempt in range(3):
            raw = _chat(messages)
            claims = _parse_json(raw)
            if isinstance(claims, list) and len(claims) > 0:
                break
        if isinstance(claims, list):
            for i, c in enumerate(claims):
                if isinstance(c, dict) and "text" in c:
                    c["source"] = "text"
                    c["idx"] = i
            result["claims"] = [c for c in claims if isinstance(c, dict) and "text" in c]

    # Vision analysis
    if image_path and Path(image_path).exists():
        img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
        ext = Path(image_path).suffix.lstrip('.')
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
        messages = [
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_data}"}},
                {"type": "text", "text": "分析這張圖片，提取可查核的事實聲明。"},
            ]},
        ]
        raw = _chat(messages, max_tokens=800)
        vision = _parse_json(raw)
        if isinstance(vision, dict):
            result["vision"] = vision
            for c in vision.get("claims", []):
                if isinstance(c, dict) and "text" in c:
                    c["source"] = "image"
                    c["idx"] = len(result["claims"])
                    result["claims"].append(c)

    return result


# ── Self-test ──

if __name__ == "__main__":
    fixtures = json.load(open(Path(__file__).parent.parent / "tests" / "fixtures.json"))

    print("=== Decompose test (text) ===\n")
    for fix in fixtures[:3]:
        print(f'[{fix["id"]}] {fix["text"][:50]}...')
        r = decompose(fix["text"])
        print(f'  Claims: {len(r["claims"])}')
        for c in r["claims"]:
            print(f'    [{c.get("difficulty","?")}] {c["text"][:60]}')
        print()

    # Vision test with a hero image (set ANSEROPOLIS_TEST_IMAGE to test)
    import os
    hero = os.environ.get("ANSEROPOLIS_TEST_IMAGE", "")
    if Path(hero).exists():
        print("=== Decompose test (vision) ===\n")
        r = decompose("", image_path=hero)
        if r["vision"]:
            print(f'  Description: {r["vision"].get("description", "")[:80]}')
        print(f'  Claims from image: {len(r["claims"])}')
        for c in r["claims"]:
            print(f'    [{c.get("difficulty","?")}] {c["text"][:60]}')

    print("\n✓ Decompose tests passed.")
