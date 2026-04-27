"""highlight — 重點實體提示器：從斷詞+POS提取六類實體，標記並作為查詢關鍵詞。

設計參考 CEUR-WS 2025 (NGU_Research) 的 Claim Rewriting 階段：
將聲明中的人事時地物數字特別標出，作為 focused query 的基礎。

六類實體：
  人 (person)  — CKIP: Nb / jieba: nr
  機構 (org)   — CKIP: Nc / jieba: nt
  地 (place)   — CKIP: Ncd, Nc+地名 / jieba: ns
  時 (time)    — CKIP: Nd / jieba: t
  事 (event)   — CKIP: VA,VB,VC,VD + Na 組合 / jieba: v,vn
  數字 (number)— CKIP: Neu,Nf / jieba: m,q / regex 補充
"""

import re

# ── CKIP POS → 實體類別映射 ──

_POS_MAP = {
    # 人
    "Nb": "person", "nr": "person", "NR": "person",
    # 機構
    "Nc": "org", "nt": "org", "NT": "org",
    # 地
    "Ncd": "place", "ns": "place", "NS": "place",
    # 時間
    "Nd": "time", "t": "time",
    # 數字/量詞
    "Neu": "number", "Nf": "number", "m": "number", "q": "number",
}

# 事件：動詞類 POS（需與名詞組合才有意義，單獨保留長度>=2的）
_EVENT_POS = {"VA", "VB", "VC", "VD", "VH", "VJ", "v", "vn"}

# 數字 regex（補捉 POS 漏掉的）
_NUM_RE = re.compile(
    r"[\d,]+\.?\d*\s*[%％萬億兆千百十]?"
    r"|[零一二三四五六七八九十百千萬億兆]+[%％]?"
    r"|\d+/\d+"
)


def extract_entities(ws: list[str], pos: list[str]) -> list[dict]:
    """從斷詞+POS結果提取六類實體。

    Returns:
        [{"text": "蔡英文", "type": "person", "idx": 3}, ...]
    """
    entities = []
    seen = set()

    for i, (w, p) in enumerate(zip(ws, pos)):
        if len(w.strip()) == 0:
            continue

        etype = _POS_MAP.get(p)

        if etype and len(w) >= 2:
            key = (w, etype)
            if key not in seen:
                seen.add(key)
                entities.append({"text": w, "type": etype, "idx": i})

        elif p in _EVENT_POS and len(w) >= 2:
            key = (w, "event")
            if key not in seen:
                seen.add(key)
                entities.append({"text": w, "type": "event", "idx": i})

    # Regex 補充數字（只補 POS 漏掉的，且不是已有實體的子串）
    existing_texts = {e["text"] for e in entities}
    full_text = "".join(ws)
    for m in _NUM_RE.finditer(full_text):
        num = m.group().strip()
        if num and len(num) >= 2 and num not in existing_texts:
            # 跳過已有實體的子串
            if any(num in t for t in existing_texts):
                continue
            existing_texts.add(num)
            entities.append({"text": num, "type": "number", "idx": -1})

    return entities


def entity_queries(entities: list[dict]) -> list[str]:
    """從實體列表生成查詢用關鍵詞（去重、優先人/機構/地/數字）。

    CEUR-WS 2025 的 Claim Rewriting：把聲明改寫為 focused question。
    這裡簡化為：提取最重要的實體作為搜尋詞組合。
    """
    # 優先順序：人/機構 > 地 > 數字 > 時間 > 事件
    priority = {"person": 0, "org": 1, "place": 2, "number": 3, "time": 4, "event": 5}
    sorted_ents = sorted(entities, key=lambda e: priority.get(e["type"], 9))

    queries = []
    seen = set()
    for e in sorted_ents:
        t = e["text"]
        if t not in seen and len(t) >= 2:
            seen.add(t)
            queries.append(t)

    return queries[:8]


def highlight_text(text: str, entities: list[dict]) -> str:
    """在原文中標記實體位置（用 <mark> 標籤），供 HTML 渲染用。"""
    # 按文字長度降序排列避免短詞覆蓋長詞
    sorted_ents = sorted(entities, key=lambda e: -len(e["text"]))

    _TYPE_CLASS = {
        "person": "hl-person",
        "org": "hl-org",
        "place": "hl-place",
        "time": "hl-time",
        "number": "hl-number",
        "event": "hl-event",
    }

    result = text
    for e in sorted_ents:
        cls = _TYPE_CLASS.get(e["type"], "hl-event")
        # 只替換第一次出現（避免重複標記）
        marked = f'<mark class="{cls}">{e["text"]}</mark>'
        result = result.replace(e["text"], marked, 1)

    return result
