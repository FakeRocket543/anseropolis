"""anseropolis.run — CLI runner: ingest → match → decompose → retrieve → package"""

import argparse
import sys
import time
import traceback
from pathlib import Path

from src.config import OUTPUT_DIR


def _log(msg: str):
    print(f"🪿 {msg}", flush=True)


def run(text: str, output_dir: str = None, theme: str = None) -> dict:
    """Run full pipeline on text. Returns package dict."""
    from src.ingest import ingest
    from src.ingest import embed_text
    from src.match import match
    from src.decompose import decompose
    from src.retrieve import retrieve
    from src.package import package, save

    if output_dir is None:
        output_dir = str(OUTPUT_DIR)

    _log(f"收到文字（{len(text)} 字）")
    t0 = time.time()

    # 1. Ingest
    _log("入料中… (CKIP + embedding)")
    ingest_result = ingest(text)
    _log(f"  斷詞完成，關鍵詞：{' '.join(ingest_result.get('keywords', [])[:5])}")

    # 2. Enrich (Wikipedia KG)
    _log("查詢實體背景… (Wikipedia)")
    enrich_result = None
    try:
        from src.enrich import enrich
        entities = [w for w, p in zip(ingest_result.get("ws", []), ingest_result.get("pos", []))
                    if p in ("Nb", "Nc", "Ncd") and len(w) >= 2][:8]
        if not entities:
            entities = ingest_result.get("keywords", [])[:5]
        if entities:
            enrich_result = enrich(entities)
            found = [e["name"] for e in enrich_result.get("entities", []) if e.get("found")]
            _log(f"  找到 {len(found)} 個實體：{', '.join(found[:5])}")
        else:
            _log("  無實體可查詢")
    except Exception:
        _log("  ⚠ Wikipedia 查詢失敗，繼續")

    # 3. Match
    _log("比對謠言庫…")
    embedding = ingest_result.get("embedding")
    keywords = ingest_result.get("keywords", [])
    match_result = match(query_embedding=embedding, top_k=5, keywords=keywords)
    top = match_result[0] if match_result else None
    if top:
        _log(f"  最佳比對：sim={top['similarity']:.4f} [{top['match_type']}] {top['title'][:40]}")
    else:
        _log("  無比對結果")

    # 4. Decompose
    _log("拆解聲明… (LLM)")
    decompose_result = {"claims": []}
    try:
        decompose_result = decompose(text)
        claims = decompose_result.get("claims", [])
        _log(f"  拆出 {len(claims)} 則聲明")
    except ConnectionError:
        _log("  ⏭ LLM 不可用，跳過聲明拆解（留給 IDE agent 處理）")
        claims = []

    # 4.5 Claim-level match（每個聲明分別比對謠言庫）
    if claims:
        _log("逐條比對謠言庫…")
        for c in claims:
            try:
                c_emb = embed_text(c["text"]) if embed_text else None
                c_kws = c["text"].split()
                c_matches = match(query_embedding=c_emb, top_k=2, keywords=c_kws)
                c["rumor_matches"] = c_matches
                if c_matches and c_matches[0]["similarity"] > 0.7:
                    top = c_matches[0]
                    _log(f"  📌 「{c['text'][:25]}」→ sim={top['similarity']:.3f} {top['title'][:30]}")
                else:
                    _log(f"  🆕 「{c['text'][:25]}」→ 謠言庫無高度相似")
            except Exception:
                c["rumor_matches"] = []

    # 5. Retrieve
    retrieve_result = None
    if claims:
        _log("搜尋證據… (search + LLM)")
        try:
            retrieve_result = retrieve(claims, enrich_result=enrich_result)
            for c in retrieve_result:
                v = c.get("assessment", {}).get("verdict", "?")
                _log(f"  [{v}] {c['text'][:40]}")
        except ConnectionError:
            _log("  ⏭ LLM 不可用，跳過證據評估（留給 IDE agent 處理）")
        except Exception:
            _log(f"  ⚠ 證據檢索失敗，繼續組裝題目包")
            traceback.print_exc()
    elif not claims:
        _log("  ⏭ 無聲明（LLM 未啟用或無可查核內容）")

    # 5.5 Diff (NER/number/timeline structured comparison)
    if retrieve_result:
        _log("結構化比對… (NER/數字/時間線)")
        try:
            from src.diff import diff as run_diff
            retrieve_result = run_diff(retrieve_result)
            for c in retrieve_result:
                d = c.get("diff", {})
                n_issues = len(d.get("ner", [])) + len(d.get("numbers", [])) + len(d.get("timeline", []))
                _log(f"  [{d.get('verdict','?')}] {n_issues} 項差異 — {c['text'][:30]}")
        except ConnectionError:
            _log("  ⏭ LLM 不可用，跳過結構化比對")
        except Exception:
            _log("  ⚠ 結構化比對失敗，繼續")

    # 6. Score
    from src.score import score as compute_score, highlight_text
    top_match = match_result[0] if match_result else None
    score_result = compute_score(
        text,
        tokens=ingest_result.get("ws"),
        match_result=top_match,
        claim_matches=claims if claims else None,
        retrieve_result=retrieve_result,
    )
    _log(f"可疑度：{score_result['total']}/100 ({score_result['label']})")
    if score_result["phrases"]:
        marked = highlight_text(text, score_result["phrases"])
        _log(f"  標記：{marked[:60]}")
        for p in score_result["phrases"]:
            _log(f"  ⚡ [{p['label']}] 「{p['phrase']}」")

    # 7. Package
    _log("組裝題目包…")
    pkg = package(text, ingest_result, match_result, decompose_result, retrieve_result, enrich_result)
    pkg["score"] = score_result
    md_path = save(pkg, output_dir)

    # 8. Render card (if theme specified)
    if theme:
        _log(f"產生圖卡… (theme={theme})")
        try:
            from src.render import render as render_card
            card_path = render_card(pkg, theme=theme)
            _log(f"  → {card_path}")
        except Exception as e:
            _log(f"  ⚠ 圖卡產生失敗：{e}")

    elapsed = round(time.time() - t0, 1)
    _log(f"完成！耗時 {elapsed}s → {md_path}")

    return pkg


def main():
    parser = argparse.ArgumentParser(
        description="Anseropolis 謠言查核 pipeline",
        usage="python -m src.run '網傳...' 或 python -m src.run --file input.txt",
    )
    parser.add_argument("text", nargs="?", help="待查核文字")
    parser.add_argument("--file", "-f", help="從檔案讀取文字")
    parser.add_argument("--output", "-o", default=None, help="輸出目錄 (預設: config OUTPUT_DIR)")
    parser.add_argument("--theme", "-t", default=None,
                        help="色系主題，產生 1080×1080 圖卡（推薦：slate, sky, emerald, amber, violet, rose）")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="互動問答模式，引導學生逐步完成查核")
    args = parser.parse_args()

    if args.interactive:
        from src.interactive import interactive_mode
        interactive_mode(theme=args.theme or "slate", output_dir=args.output)
        return

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        sys.exit(1)

    if not text:
        print("錯誤：輸入文字為空", file=sys.stderr)
        sys.exit(1)

    try:
        run(text, args.output, theme=args.theme)
    except KeyboardInterrupt:
        print("\n🪿 中斷。")
        sys.exit(130)
    except Exception as e:
        print(f"🪿 ❌ 執行失敗：{e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
