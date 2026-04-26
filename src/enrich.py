"""anseropolis.enrich — 用 Wikipedia/Wikidata 實際分類標記實體領域"""

import json
import time
from urllib.request import urlopen, Request
from urllib.parse import quote
from urllib.error import HTTPError
from collections import Counter

_cache = {}


def _wiki_summary(name: str) -> dict | None:
    """Fetch Wikipedia summary + Wikidata ID."""
    key = ("summary", name)
    if key in _cache:
        return _cache[key]
    try:
        url = f"https://zh.wikipedia.org/api/rest_v1/page/summary/{quote(name)}"
        req = Request(url, headers={"User-Agent": "Anseropolis/0.1"})
        data = json.loads(urlopen(req, timeout=10).read())
        result = {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "extract": data.get("extract", "")[:200],
            "wikidata_id": data.get("wikibase_item", ""),
            "wiki_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }
        _cache[key] = result
        return result
    except Exception:
        _cache[key] = None
        return None


def _wiki_categories(name: str) -> list[str]:
    """Fetch actual Wikipedia categories for an article."""
    key = ("cats", name)
    if key in _cache:
        return _cache[key]
    try:
        url = (
            f"https://zh.wikipedia.org/w/api.php?"
            f"action=query&titles={quote(name)}&prop=categories"
            f"&cllimit=20&clshow=!hidden&format=json"
        )
        req = Request(url, headers={"User-Agent": "Anseropolis/0.1"})
        data = json.loads(urlopen(req, timeout=10).read())
        pages = data.get("query", {}).get("pages", {})
        cats = []
        for page in pages.values():
            for c in page.get("categories", []):
                # Strip "Category:" prefix
                title = c["title"].replace("Category:", "").replace("分類:", "")
                cats.append(title)
        _cache[key] = cats
        return cats
    except Exception:
        _cache[key] = []
        return []


def _wikidata_claims(qid: str) -> dict:
    """Fetch key Wikidata properties: instance_of (P31), occupation (P106), country (P17)."""
    key = ("wd", qid)
    if key in _cache:
        return _cache[key]
    if not qid:
        return {}
    try:
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        req = Request(url, headers={"User-Agent": "Anseropolis/0.1"})
        data = json.loads(urlopen(req, timeout=10).read())
        entity = data.get("entities", {}).get(qid, {})
        claims = entity.get("claims", {})
        labels = entity.get("labels", {})

        def get_label(qid_inner):
            """Try to get zh label for a Wikidata entity."""
            for lang in ["zh-tw", "zh-hant", "zh", "en"]:
                l = labels.get(lang, {}).get("value")
                if l:
                    return l
            return qid_inner

        def extract_values(prop):
            vals = []
            for claim in claims.get(prop, []):
                ms = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(ms, dict) and "id" in ms:
                    vals.append(ms["id"])
                elif isinstance(ms, dict) and "text" in ms:
                    vals.append(ms["text"])
            return vals

        result = {
            "instance_of": extract_values("P31"),      # 是什麼
            "occupation": extract_values("P106"),       # 職業
            "country": extract_values("P17"),           # 國家
            "party": extract_values("P102"),            # 政黨
            "industry": extract_values("P452"),         # 產業
        }
        _cache[key] = result
        return result
    except Exception:
        _cache[key] = {}
        return {}


def enrich_entity(name: str) -> dict:
    """Look up a single entity in Wikipedia + Wikidata."""
    wiki = _wiki_summary(name)
    if not wiki:
        return {"name": name, "found": False}

    cats = _wiki_categories(name)
    wd = _wikidata_claims(wiki.get("wikidata_id", ""))

    return {
        "name": name,
        "found": True,
        "description": wiki["description"],
        "extract": wiki["extract"],
        "wikidata_id": wiki["wikidata_id"],
        "wiki_url": wiki["wiki_url"],
        "categories": cats,
        "wikidata": wd,
    }


def enrich(entities: list[str]) -> dict:
    """Enrich entity list with Wikipedia KG.
    
    Returns: {entities: [...], all_categories: [...], wikidata_types: [...]}
    """
    results = []
    all_cats = []
    all_wd_types = []

    for name in entities:
        if len(name) < 2:
            continue
        r = enrich_entity(name)
        results.append(r)
        if r.get("found"):
            all_cats.extend(r.get("categories", []))
            all_wd_types.extend(r.get("wikidata", {}).get("instance_of", []))
        time.sleep(0.15)  # rate limit

    return {
        "entities": results,
        "all_categories": dict(Counter(all_cats).most_common(20)),
        "wikidata_types": all_wd_types,
    }


# ── Self-test ──

if __name__ == "__main__":
    test_cases = [
        ["賴清德", "民進黨"],
        ["台積電", "半導體"],
        ["馬克宏", "北約"],
    ]

    for names in test_cases:
        print(f"\n{'='*50}")
        print(f"Query: {names}")
        r = enrich(names)
        for e in r["entities"]:
            if e.get("found"):
                print(f"\n  ✓ {e['name']}")
                print(f"    desc: {e['description']}")
                print(f"    wiki cats: {e['categories'][:5]}")
                print(f"    wikidata: {e.get('wikidata', {})}")
            else:
                print(f"\n  ✗ {e['name']}: not found")
        print(f"\n  Top categories: {r['all_categories']}")

    print("\n✓ Enrich tests passed.")
