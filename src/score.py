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
        "political": scan_political(text, tokens),
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


# ── Political Spectrum (from cross-topic BM25 analysis) ──

_POLITICAL_INDICATORS = {
    "cn_official": {
        "同胞": 3.0, "融合": 2.5, "當局": 2.5, "分裂": 2.0,
        "頑固": 3.0, "箇中": 3.0, "廣大": 1.5, "祖國": 3.0,
        "統一": 1.5, "台獨": 2.0, "民進黨當局": 3.0,
        "兩岸關係和平發展": 2.0, "台灣同胞": 2.5,
        "堅決反對": 2.0, "勢力": 1.0, "深化": 1.0,
    },
    "cn_media": {
        "中方": 2.0, "特朗普": 3.0, "同比": 2.0, "一季度": 2.0,
        "高質量發展": 2.5, "新質生產力": 3.0, "人民群眾": 2.0,
        "黨中央": 2.5, "總書記": 2.0,
    },
    "tw_blue_cn": {
        "大陸": 2.0, "兄弟": 1.5, "促統": 3.0, "崛起": 1.5,
        "陸客": 2.0, "陸方": 2.0,
    },
    "tw_blue": {
        "中華民國": 1.5, "偽政權": 3.0,
        "大陸": 1.5, "國民黨": 1.0, "民進黨": 1.0,
    },
    "tw_green": {
        "中國": 1.0, "中共": 1.5, "主權": 2.5, "民主": 1.5,
        "假訊息": 2.0, "威脅": 1.0, "國際空間": 2.0, "打壓": 1.5,
    },
    "anti_ccp": {
        "中共": 2.0, "迫害": 3.0, "法輪功": 3.0, "神韻": 3.0,
        "極權": 2.5, "暴政": 3.0, "中共政權": 3.0,
        "習近平政權": 2.5, "滲透": 2.0,
    },
}

_SPECTRUM_LABELS = {
    "cn_official": "中共官方",
    "cn_media": "中共官媒",
    "tw_blue_cn": "親中藍",
    "tw_blue": "藍營",
    "tw_green": "偏綠",
    "anti_ccp": "反共",
}


def scan_political(text: str, tokens: list[str] = None) -> dict:
    """Score text on political spectrum using TF-IDF fingerprints + indicator lexicon.

    Returns:
        {"group": str, "label": str, "score": float,
         "all_scores": {group: score}, "hits": {group: [terms]},
         "tfidf_scores": {source: cosine_sim}}
    """
    # --- Layer 1: TF-IDF fingerprint cosine similarity ---
    tfidf_scores = _tfidf_classify(text)

    # --- Layer 2: Indicator lexicon (hard signals) ---
    lex_scores = {}
    hits = {}
    for group, lexicon in _POLITICAL_INDICATORS.items():
        s = 0.0
        matched = []
        for term, weight in lexicon.items():
            if term in text:
                s += weight
                matched.append(term)
        lex_scores[group] = s
        hits[group] = matched

    # --- Combine: lexicon dominates if strong, else use TF-IDF ---
    top_lex_group = max(lex_scores, key=lex_scores.get)
    top_lex_score = lex_scores[top_lex_group]

    if top_lex_score >= 3.0:
        # Strong lexicon signal → use it
        group = top_lex_group
        score_val = top_lex_score
    elif tfidf_scores:
        # Use TF-IDF grouping
        group_tfidf = _aggregate_tfidf_by_group(tfidf_scores)
        top_tfidf_group = max(group_tfidf, key=group_tfidf.get)
        if group_tfidf[top_tfidf_group] > 0.02:
            group = top_tfidf_group
            score_val = group_tfidf[top_tfidf_group] * 10  # scale to ~0-10
        else:
            group = "neutral"
            score_val = 0
    else:
        group = "neutral"
        score_val = 0

    label = _SPECTRUM_LABELS.get(group, "中立")

    return {
        "group": group,
        "label": label,
        "score": round(score_val, 2),
        "all_scores": lex_scores,
        "hits": {g: h for g, h in hits.items() if h},
        "tfidf_scores": tfidf_scores,
    }


# ── TF-IDF fingerprint matching ──

_POLITICAL_FP: dict = {}
_POLITICAL_FP_PATH = Path(__file__).parent.parent / "data" / "political_fingerprints.json"

_GROUP_MAP = {
    "tao": "cn_official", "people": "cn_official",
    "huanqiu": "cn_media",
    "wantdaily": "tw_blue_cn",
    "ct": "tw_blue", "cnews": "tw_blue",
    "ettoday": "tw_neutral",
    "ltn": "tw_green",
    "epoch": "anti_ccp",
    "rumor": "rumor",
}


def _load_political_fp():
    global _POLITICAL_FP
    if _POLITICAL_FP:
        return
    import json as _json
    if _POLITICAL_FP_PATH.exists():
        data = _json.load(open(_POLITICAL_FP_PATH))
        _POLITICAL_FP = data.get("fingerprints", {})


def _tfidf_classify(text: str) -> dict:
    """Compute cosine similarity between text TF and each source's TF-IDF profile."""
    _load_political_fp()
    if not _POLITICAL_FP:
        return {}

    import re as _re
    try:
        import jieba as _jieba
        import opencc as _opencc
        _cc = _opencc.OpenCC("s2t")
        text = _cc.convert(text)
        tokens = [w for w in _jieba.cut(text)
                  if len(w) >= 2 and _re.fullmatch(r'[\u4e00-\u9fff]+', w)]
    except ImportError:
        tokens = list(text)

    if not tokens:
        return {}

    tf = {}
    total = len(tokens)
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    for t in tf:
        tf[t] /= total

    # Cosine similarity with each source fingerprint
    scores = {}
    for source, fp in _POLITICAL_FP.items():
        dot = sum(tf.get(w, 0) * s for w, s in fp.items())
        norm_fp = sum(s * s for s in fp.values()) ** 0.5
        norm_tf = sum(v * v for v in tf.values()) ** 0.5
        if norm_fp > 0 and norm_tf > 0:
            scores[source] = dot / (norm_fp * norm_tf)
        else:
            scores[source] = 0.0

    return scores


def _aggregate_tfidf_by_group(tfidf_scores: dict) -> dict:
    """Aggregate per-source TF-IDF scores into group scores."""
    group_scores = {}
    group_counts = {}
    for source, sim in tfidf_scores.items():
        g = _GROUP_MAP.get(source, source)
        group_scores[g] = group_scores.get(g, 0) + sim
        group_counts[g] = group_counts.get(g, 0) + 1
    # Average per group
    return {g: group_scores[g] / group_counts[g] for g in group_scores}


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
        pol = r["political"]
        print(f"\n{'='*60}")
        print(f"📝 {text}")
        print(f"   分數: {r['total']}/100 ({r['label']})")
        print(f"   政治光譜: {pol['label']} ({pol['score']:.1f})")
        if pol.get("hits"):
            for g, terms in pol["hits"].items():
                if terms:
                    print(f"     {_SPECTRUM_LABELS[g]}: {', '.join(terms)}")
        if phrases:
            print(f"   可疑語句:")
            for p in phrases:
                print(f"     [{p['label']}] 「{p['phrase']}」(+{p['weight']})")
        else:
            print(f"   ✅ 無可疑語句")
