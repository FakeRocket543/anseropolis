"""anseropolis.score — 可疑度評分 + 可疑語句標記（基於斷詞 + 詞典比對）"""

from pathlib import Path

import yaml

# ── Load lexicons ──

_LEXICON_PATH = Path(__file__).parent.parent / "data" / "suspect_lexicon.yaml"
_TAO_PATH = Path(__file__).parent.parent / "data" / "tao_lexicon.yaml"
_TAO_FP_PATH = Path(__file__).parent.parent / "data" / "tao_fingerprints.json"
_LEXICON: dict = {}
_TAO_LEXICON: dict = {}
_TAO_FP: dict = {}


def _load_lexicon():
    global _LEXICON, _TAO_LEXICON, _TAO_FP
    if _LEXICON:
        return
    with open(_LEXICON_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    for label, info in raw.items():
        weight = info["weight"]
        for term in info["terms"]:
            _LEXICON[term] = (label, weight)
    # TAO lexicon (categorical)
    with open(_TAO_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    for label, info in raw.items():
        weight = info["weight"]
        for term in info["terms"]:
            _TAO_LEXICON[term] = (label, weight)
    # TAO fingerprints (frequency-based)
    import json
    with open(_TAO_FP_PATH, encoding="utf-8") as f:
        _TAO_FP = json.load(f)


def _ngrams(tokens: list[str], max_n: int = 4) -> list[tuple[str, int, int]]:
    """Generate n-grams from token list. Returns (text, start_idx, end_idx).
    Also generates prefix combinations for partial matches."""
    results = []
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            gram = "".join(tokens[i:i + n])
            results.append((gram, i, i + n))
    # Also check: last token truncated (e.g. "快"+"轉給" → "快轉")
    for i in range(len(tokens) - 1):
        for prefix_len in range(1, min(4, len(tokens[i + 1])) + 1):
            gram = tokens[i] + tokens[i + 1][:prefix_len]
            results.append((gram, i, i + 2))
    return results


def scan_phrases(text: str, tokens: list[str] = None) -> list[dict]:
    """Scan text using CKIP tokens + lexicon lookup."""
    return _scan_with_lexicon(text, tokens, _LEXICON)


def scan_tao(text: str, tokens: list[str] = None) -> list[dict]:
    """Scan text for TAO (國台辦) narrative phrases."""
    return _scan_with_lexicon(text, tokens, _TAO_LEXICON)


def _scan_with_lexicon(text: str, tokens: list[str], lexicon: dict) -> list[dict]:
    """Scan text using CKIP tokens + given lexicon."""
    _load_lexicon()

    if tokens is None:
        # Fallback: treat each char as token (for when CKIP unavailable)
        tokens = list(text)

    hits = []
    seen_spans = set()

    # Pre-compute token char offsets
    offsets = []  # (char_start, char_end) for each token
    pos = 0
    for t in tokens:
        start = text.find(t, pos)
        if start == -1:
            start = pos  # fallback
        offsets.append((start, start + len(t)))
        pos = start + len(t)

    # Check all n-grams against lexicon
    for gram, start_idx, end_idx in _ngrams(tokens):
        if gram in lexicon:
            span_key = (start_idx, end_idx)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                label, weight = lexicon[gram]
                char_start = offsets[start_idx][0]
                char_end = offsets[end_idx - 1][1]
                hits.append({
                    "phrase": gram,
                    "label": label,
                    "weight": weight,
                    "start": char_start,
                    "end": char_end,
                })

    # Deduplicate overlapping (keep higher weight)
    hits.sort(key=lambda h: (-h["weight"], h["start"]))
    used = set()
    unique = []
    for h in hits:
        span = range(h["start"], h["end"])
        if not any(i in used for i in span):
            used.update(span)
            unique.append(h)
    unique.sort(key=lambda h: h["start"])
    return unique


def score(text: str, tokens: list[str] = None,
          match_result: dict | None = None,
          claim_matches: list | None = None,
          retrieve_result: list | None = None) -> dict:
    """Compute suspicion score 0-100 with breakdown.

    Args:
        text: original text
        tokens: CKIP segmentation result
        match_result: top match from rumor DB
        claim_matches: claims with top_match info
        retrieve_result: retrieve results with assessments
    """
    # 1. Linguistic score (0-40)
    phrases = scan_phrases(text, tokens)
    ling_raw = sum(p["weight"] for p in phrases)
    ling_score = min(40, ling_raw * 5)

    # 1b. TAO narrative score (separate axis)
    tao_phrases = scan_tao(text, tokens)
    tao_raw = sum(p["weight"] for p in tao_phrases)
    tao_score = min(40, tao_raw * 5)

    # 2. Rumor similarity (0-25)
    sim = 0
    if match_result:
        sim = match_result.get("similarity", 0)
    sim_score = max(0, min(25, int((sim - 0.6) * 100)))

    # 3. Claim-match rate (0-20)
    claim_score = 0
    if claim_matches:
        high_matches = sum(1 for c in claim_matches
                          if c.get("top_match", {}).get("similarity", 0) > 0.7)
        total = len(claim_matches)
        if total > 0:
            claim_score = int((high_matches / total) * 20)

    # 4. Refuted rate from retrieve (0-15)
    verdict_score = 0
    if retrieve_result:
        refuted = sum(1 for c in retrieve_result
                      if c.get("assessment", {}).get("verdict") == "refuted")
        total = len(retrieve_result)
        if total > 0:
            verdict_score = int((refuted / total) * 15)

    total_score = ling_score + sim_score + claim_score + verdict_score

    if total_score >= 70:
        level, label_zh = "high", "高度可疑"
    elif total_score >= 40:
        level, label_zh = "medium", "中度可疑"
    elif total_score >= 20:
        level, label_zh = "low", "輕度可疑"
    else:
        level, label_zh = "minimal", "可疑度低"

    return {
        "total": total_score,
        "level": level,
        "label": label_zh,
        "breakdown": {
            "linguistic": ling_score,
            "rumor_similarity": sim_score,
            "claim_match": claim_score,
            "verdict_refuted": verdict_score,
        },
        "phrases": phrases,
        "tao": {
            "score": tao_score,
            "phrases": tao_phrases,
        },
    }


def highlight_text(text: str, phrases: list[dict]) -> str:
    """Return text with suspicious phrases marked with【】."""
    if not phrases:
        return text
    result = text
    for p in reversed(phrases):
        s, e = p["start"], p["end"]
        result = result[:s] + f"【{result[s:e]}】" + result[e:]
    return result


# ── Self-test ──

if __name__ == "__main__":
    # Simulate CKIP tokens
    tests = [
        ("網傳美國已正式宣布放棄台灣，快轉給親友知道",
         ["網傳", "美國", "已", "正式", "宣布", "放棄", "台灣", "，", "快轉", "給", "親友", "知道"]),
        ("陸軍金六結又出事！營長播統戰片遭懲處 顧立雄：加強精神教育",
         ["陸軍", "金六結", "又", "出事", "！", "營長", "播", "統戰片", "遭", "懲處", "顧立雄", "：", "加強", "精神", "教育"]),
        ("震驚！醫生不告訴你的真相：吃這個水果絕對治癌症，趕快分享",
         ["震驚", "！", "醫生", "不", "告訴", "你", "的", "真相是", "：", "吃", "這個", "水果", "絕對", "治", "癌症", "，", "趕快", "分享"]),
        ("據了解，不願具名的消息人士透露，政府正在隱瞞，主流媒體不報導",
         ["據了解", "，", "不願具名", "的", "消息人士", "透露", "，", "政府", "正在", "隱瞞", "，", "主流媒體", "不報", "導"]),
        ("王崑義/自導自演？ 台美領導人還能玩多久",
         ["王崑義", "/", "自導自演", "？", "台美", "領導人", "還", "能", "玩", "多久"]),
    ]

    for text, tokens in tests:
        r = score(text, tokens=tokens)
        phrases = r["phrases"]
        print(f"\n{'='*60}")
        print(f"📝 {text}")
        print(f"   分數: {r['total']}/100 ({r['label']})")
        if phrases:
            print(f"   可疑語句:")
            for p in phrases:
                print(f"     [{p['label']}] 「{p['phrase']}」(+{p['weight']})")
            print(f"   標記: {highlight_text(text, phrases)}")
        else:
            print(f"   ✅ 無可疑語句")
