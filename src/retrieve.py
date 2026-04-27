"""anseropolis.retrieve — 證據檢索：搜尋 + LLM 評估"""

import json
from src.llm import chat as _chat
import re
from html import unescape
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import urlopen, Request

SEARXNG_URL = "http://localhost:8888/search"
DDG_URL = "https://html.duckduckgo.com/html/"

MAX_RESULTS = 5

# ── Engine routing by domain ──

DOMAIN_ENGINES = {
    "medical": "google news,pubmed,google scholar",
    "science": "google news,arxiv,google scholar,semantic scholar",
    "military": "google news,bing news,brave.news,wikinews",
    "politics": "google news,bing news,brave.news,wikinews",
    "china": "google news,bing news,sogou wechat,baidu",
    "international": "google news,bing news,reuters,brave.news",
    "finance": "google news,bing news",
    "entertainment": "google news,bing news,youtube",
}

DOMAIN_LANG = {
    "china": "zh-CN",
}

# Category keywords → domain
_CAT_DOMAIN_MAP = {
    "醫": "medical", "藥": "medical", "疾病": "medical", "健康": "medical",
    "生物": "science", "物理": "science", "化學": "science", "科技": "science",
    "軍事": "military", "國防": "military", "武器": "military", "戰爭": "military",
    "政治": "politics", "政黨": "politics", "選舉": "politics", "立法": "politics",
    "中華人民共和國": "china", "中国": "china", "中國大陸": "china",
    "經濟": "finance", "金融": "finance", "股票": "finance",
    "演員": "entertainment", "歌手": "entertainment", "電影": "entertainment",
}

_COUNTRY_DOMAIN_MAP = {
    "Q148": "china",  # 中華人民共和國
}


def route_engines(enrich_result: dict | None) -> tuple[str, str]:
    """Pick SearXNG engines + language based on KG categories/country.
    Returns (engines_csv, language)."""
    if not enrich_result:
        return ("", "zh-TW")

    # Collect all categories
    cats = list((enrich_result.get("all_categories") or {}).keys())
    # Collect countries from wikidata
    countries = set()
    for e in enrich_result.get("entities", []):
        for c in e.get("wikidata", {}).get("country", []):
            countries.add(c)

    # Match domain: country first, then categories
    domain = None
    for c in countries:
        if c in _COUNTRY_DOMAIN_MAP:
            domain = _COUNTRY_DOMAIN_MAP[c]
            break

    # Category refines (medical/science override country)
    for cat in cats:
        for kw, d in _CAT_DOMAIN_MAP.items():
            if kw in cat:
                if d in ("medical", "science") or not domain:
                    domain = d
                break
        if domain and domain not in ("china", "international"):
            break

    engines = DOMAIN_ENGINES.get(domain, "")
    lang = DOMAIN_LANG.get(domain, "zh-TW")
    return (engines, lang)


def _searxng(query: str, engines: str = "", language: str = "zh-TW") -> list[dict]:
    """SearXNG JSON API."""
    url = f"{SEARXNG_URL}?q={quote_plus(query)}&format=json&language={language}"
    if engines:
        url += f"&engines={quote_plus(engines)}"
    req = Request(url, headers={"Accept": "application/json"})
    resp = urlopen(req, timeout=15)
    data = json.loads(resp.read())
    results = []
    for r in data.get("results", [])[:MAX_RESULTS]:
        results.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("content", "")[:300],
            "source_type": _classify_source(r.get("url", "")),
            "retrieved_by": "searxng",
        })
    return results


def _duckduckgo(query: str) -> list[dict]:
    """DuckDuckGo HTML scraping fallback."""
    url = f"{DDG_URL}?q={quote_plus(query)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urlopen(req, timeout=15)
    html = resp.read().decode("utf-8", errors="replace")
    results = []
    # Extract result blocks: each has class="result__a" for link/title and "result__snippet" for snippet
    for m in re.finditer(
        r'class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:td|div|span)',
        html, re.DOTALL,
    ):
        u = unescape(m.group("url"))
        # DDG wraps URLs in a redirect; extract actual URL
        real = re.search(r'uddg=([^&]+)', u)
        if real:
            from urllib.parse import unquote
            u = unquote(real.group(1))
        title = re.sub(r'<[^>]+>', '', unescape(m.group("title")))
        snippet = re.sub(r'<[^>]+>', '', unescape(m.group("snippet")))[:300]
        results.append({
            "url": u, "title": title, "snippet": snippet,
            "source_type": _classify_source(u),
            "retrieved_by": "duckduckgo",
        })
        if len(results) >= MAX_RESULTS:
            break
    return results


def _classify_source(url: str) -> str:
    url_l = url.lower()
    if any(d in url_l for d in (".gov", ".gov.tw", "state.gov")):
        return "government"
    if any(d in url_l for d in ("reuters", "apnews", "bbc", "cna.com.tw", "ltn.com.tw", "udn.com")):
        return "news"
    if any(d in url_l for d in ("tfc-taiwan", "cofacts", "mygopen", "factcheck")):
        return "factcheck"
    if any(d in url_l for d in ("wikipedia", "wiki")):
        return "reference"
    return "web"


def search(query: str, enrich_result: dict | None = None) -> list[dict]:
    """Search via SearXNG (with engine routing), fall back to DuckDuckGo."""
    engines, lang = route_engines(enrich_result)
    try:
        results = _searxng(query, engines=engines, language=lang)
        if results:
            return results
    except (URLError, OSError, TimeoutError):
        pass
    try:
        return _duckduckgo(query)
    except (URLError, OSError, TimeoutError):
        return []


# ── LLM assessment ──

ASSESS_PROMPT = """你是事實查核助手。根據提供的證據，判斷聲明的真實性。

聲明：{claim}

證據：
{evidence}

請用以下 JSON 格式回覆（不要加其他文字）：
{{"verdict": "supported 或 refuted 或 insufficient", "reason": "簡短理由"}}"""


def assess(claim_text: str, evidence: list[dict]) -> dict:
    """Use LLM to assess claim against evidence."""
    if not evidence:
        return {"verdict": "insufficient", "reason": "無搜尋結果"}
    ev_text = "\n".join(
        f"[{i+1}] {e['title']}: {e['snippet']}" for i, e in enumerate(evidence)
    )
    prompt = ASSESS_PROMPT.format(claim=claim_text, evidence=ev_text)
    raw = _chat([{"role": "user", "content": prompt}])
    # Parse JSON from response
    raw = re.sub(r'```json\s*', '', raw)
    raw = re.sub(r'```\s*', '', raw)
    try:
        obj = json.loads(raw[raw.index('{'):])
    except (json.JSONDecodeError, ValueError):
        # Fallback: look for verdict keyword
        for v in ("supported", "refuted", "insufficient"):
            if v in raw.lower():
                return {"verdict": v, "reason": raw[:200]}
        return {"verdict": "insufficient", "reason": raw[:200]}
    return {
        "verdict": obj.get("verdict", "insufficient"),
        "reason": obj.get("reason", ""),
    }


# ── Main entry ──

def retrieve(claims: list[dict], enrich_result: dict | None = None) -> list[dict]:
    """Search evidence and assess each claim.

    Args:
        claims: list of dicts with at least 'text'; optionally 'keywords', 'search_suggestions'.
        enrich_result: output from enrich() for engine routing.
    Returns:
        list of dicts: each claim enriched with 'evidence' and 'assessment'.
    """
    results = []
    for claim in claims:
        text = claim.get("text", "")
        # Build query from keywords or search_suggestions, fall back to claim text
        keywords = claim.get("keywords") or claim.get("search_suggestions")
        query = " ".join(keywords) if keywords else text

        evidence = search(query, enrich_result=enrich_result)
        assessment = assess(text, evidence)

        results.append({
            **claim,
            "evidence": evidence,
            "assessment": assessment,
        })
    return results


# ── Self-test ──

if __name__ == "__main__":
    sample_claims = [
        {
            "idx": 0,
            "text": "美國已正式宣布放棄台灣",
            "keywords": ["美國", "放棄", "台灣", "2026"],
        },
        {
            "idx": 1,
            "text": "吃隔夜飯會產生大量黃麴毒素導致癌症",
            "keywords": ["隔夜飯", "黃麴毒素", "致癌"],
        },
        {
            "idx": 2,
            "text": "台積電確定整廠搬遷美國",
            "keywords": ["台積電", "搬遷", "美國"],
        },
    ]

    print("=== Retrieve self-test ===\n")
    for claim in sample_claims:
        print(f"[{claim['idx']}] {claim['text']}")
        query = " ".join(claim.get("keywords", [claim["text"]]))
        evidence = search(query)
        print(f"  搜尋結果: {len(evidence)} 筆")
        for e in evidence[:3]:
            print(f"    [{e['retrieved_by']}] {e['title'][:50]}")
            print(f"      {e['snippet'][:80]}...")
        if evidence:
            print("  LLM 評估中...")
            a = assess(claim["text"], evidence)
            print(f"  判定: {a['verdict']} — {a['reason'][:80]}")
        else:
            print("  ⚠ 無搜尋結果，跳過 LLM 評估")
        print()

    print("✓ Retrieve self-test complete.")
