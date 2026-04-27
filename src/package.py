"""anseropolis.package — 組裝題目包：pipeline 結果 → dict + markdown"""

import json
import hashlib
from datetime import datetime
from pathlib import Path

VERDICT_MAP = {
    "supported": "✅ 有證據支持",
    "refuted": "❌ 證據反駁",
    "insufficient": "⚠️ 證據不足",
}

STATUS_EMOJI = {
    "supported": "✅",
    "refuted": "❌",
    "insufficient": "⚠️",
}


def _summary(text: str, max_len: int = 40) -> str:
    """First line, truncated."""
    line = text.strip().split("\n")[0]
    return line[:max_len] + ("…" if len(line) > max_len else "")


def _fingerprint_text(fp: dict) -> str:
    hits = [k for k, v in fp.items() if v]
    return "、".join(hits) if hits else "無明顯特徵"


def _gaps(claims: list) -> list[str]:
    """Identify what's still missing."""
    gaps = []
    no_evidence = [c for c in claims if not c.get("evidence")]
    insufficient = [c for c in claims if c.get("assessment", {}).get("verdict") == "insufficient"]
    if no_evidence:
        gaps.append(f"{len(no_evidence)} 則聲明尚無搜尋結果")
    if insufficient:
        gaps.append(f"{len(insufficient)} 則聲明證據不足，需人工查證")
    hard = [c for c in claims if c.get("difficulty") == "hard"]
    if hard:
        gaps.append(f"{len(hard)} 則高難度聲明需專家判斷")
    return gaps


def package(text: str, ingest_result: dict = None, match_result: list = None,
            decompose_result: dict = None, retrieve_result: list = None,
            enrich_result: dict = None) -> dict:
    """Assemble topic package from pipeline stage results.

    All stage results are optional — produces best-effort package with whatever is available.
    """
    ts = datetime.now().isoformat(timespec="seconds")
    slug = hashlib.md5(text.encode()).hexdigest()[:8]
    summary = _summary(text)

    # Merge retrieve results back into claims
    claims = []
    if decompose_result:
        claims = list(decompose_result.get("claims", []))
    if retrieve_result:
        # retrieve_result is enriched claims list — use it directly
        claims = retrieve_result

    pkg = {
        "summary": summary,
        "slug": slug,
        "timestamp": ts,
        "text": text,
        "ingest": ingest_result,
        "enrich": enrich_result,
        "matches": match_result or [],
        "claims": claims,
        "gaps": _gaps(claims),
    }
    return pkg


def to_markdown(pkg: dict) -> str:
    """Render package dict as markdown report."""
    lines = [f"# 題目包：{pkg['summary']}", ""]

    # 原始訊息
    lines += ["## 原始訊息", "", pkg["text"], ""]

    # 語言指紋
    lines += ["## 語言指紋", ""]
    ingest = pkg.get("ingest") or {}
    fp = ingest.get("fingerprint", {})
    if fp:
        lines.append(_fingerprint_text(fp))
    kws = ingest.get("keywords", [])
    if kws:
        lines.append(f"\n關鍵詞：{' / '.join(kws)}")
    lines.append("")

    # 實體背景 (Wikipedia KG)
    enrich = pkg.get("enrich")
    if enrich and enrich.get("entities"):
        lines += ["## 實體背景", ""]
        lines.append("| 實體 | 說明 | Wikipedia 分類 | 來源 |")
        lines.append("|------|------|---------------|------|")
        for e in enrich["entities"]:
            if not e.get("found"):
                continue
            name = e["name"]
            desc = e.get("description", "")[:30]
            cats = ", ".join(e.get("categories", [])[:3]) or "—"
            url = e.get("wiki_url", "")
            link = f"[維基百科]({url})" if url else "—"
            lines.append(f"| {name} | {desc} | {cats} | {link} |")
        lines.append("")

    # 謠言庫比對
    lines += ["## 謠言庫比對", ""]
    matches = pkg.get("matches", [])
    if matches:
        for m in matches[:5]:
            mt = m.get("match_type", "none")
            sim = m.get("similarity", 0)
            title = m.get("title", "?")
            url = m.get("url", "")
            verdict = m.get("verdict", "")
            lines.append(f"- **[{mt}]** sim={sim:.4f} {verdict} — {title}")
            if url:
                lines.append(f"  {url}")
    else:
        lines.append("（無比對結果）")
    lines.append("")

    # 聲明拆解
    lines += ["## 聲明拆解", ""]
    claims = pkg.get("claims", [])
    if claims:
        lines.append("| # | 聲明 | 證據 | 來源 | 狀態 | 謠言庫比對 |")
        lines.append("|---|------|------|------|------|-----------|")
        for i, c in enumerate(claims):
            claim_text = c.get("text", "")[:50]
            ev = c.get("evidence", [])
            ev_summary = f"{len(ev)} 筆" if ev else "—"
            sources = ", ".join(sorted({e.get("source_type", "web") for e in ev})) if ev else "—"
            assessment = c.get("assessment", {})
            verdict = assessment.get("verdict", "pending")
            status = STATUS_EMOJI.get(verdict, "⏳") + " " + verdict
            # Claim-level match
            rm = c.get("rumor_matches", [])
            if rm and rm[0].get("similarity", 0) > 0.6:
                rm_text = f"sim={rm[0]['similarity']:.2f} [{rm[0].get('match_type','')}]({rm[0].get('url','')})"
            else:
                rm_text = "—"
            lines.append(f"| {i+1} | {claim_text} | {ev_summary} | {sources} | {status} | {rm_text} |")
    else:
        lines.append("（無聲明）")
    lines.append("")

    # 還缺什麼
    lines += ["## 還缺什麼", ""]
    gaps = pkg.get("gaps", [])
    if gaps:
        for g in gaps:
            lines.append(f"- {g}")
    else:
        lines.append("所有聲明皆已有初步證據。")
    lines.append("")

    # 查核者筆記
    lines += ["## 查核者筆記", "", "（待查核者填寫）", ""]

    return "\n".join(lines)


def save(pkg: dict, output_dir: str = "output") -> Path:
    """Save package as JSON + markdown."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = pkg["slug"]
    ts = pkg["timestamp"].replace(":", "").replace("-", "")

    json_path = out / f"{slug}_{ts}.json"
    md_path = out / f"{slug}_{ts}.md"

    json_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2, default=str))
    md_path.write_text(to_markdown(pkg))

    return md_path


# ── Self-test ──

if __name__ == "__main__":
    print("=== Package self-test ===\n")

    # Simulate pipeline results
    text = "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"

    fake_ingest = {
        "fingerprint": {"網傳": True, "問號": False, "引述": False, "情緒詞": False, "來源模糊": False},
        "keywords": ["美國", "宣布", "放棄", "台灣", "F-16", "戰機", "扣留", "交付"],
    }
    fake_match = [
        {"report_id": 137781, "similarity": 0.8712, "title": "美國放棄台灣？", "verdict": "錯誤",
         "match_type": "high", "url": "https://tfc-taiwan.org.tw/articles/137781"},
    ]
    fake_claims = [
        {"text": "美國已正式宣布放棄台灣", "difficulty": "easy",
         "evidence": [{"title": "TFC查核", "snippet": "此為錯誤訊息", "source_type": "factcheck"}],
         "assessment": {"verdict": "refuted", "reason": "查核報告已闢謠"}},
        {"text": "F-16戰機全數扣留不交付", "difficulty": "medium",
         "evidence": [],
         "assessment": {"verdict": "insufficient", "reason": "無搜尋結果"}},
    ]

    pkg = package(text, fake_ingest, fake_match, retrieve_result=fake_claims)
    md = to_markdown(pkg)

    print(md)
    print("---")
    print(f"Package keys: {list(pkg.keys())}")
    print(f"Gaps: {pkg['gaps']}")

    # Test save
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = save(pkg, tmp)
        print(f"Saved to: {path}")
        print(f"File size: {path.stat().st_size} bytes")
        assert path.exists()
        assert (path.parent / path.name.replace(".md", ".json")).exists()

    print("\n✓ Package self-test passed.")
