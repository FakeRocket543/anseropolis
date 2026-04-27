"""anseropolis.interactive — 互動問答模式，引導學生完成謠言查核。"""

import sys


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"\n💬 {prompt}{suffix}\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n👋 掰掰！")
        sys.exit(0)
    return ans or default


def _pause(msg: str = "按 Enter 繼續…"):
    try:
        input(f"\n⏎ {msg}")
    except (EOFError, KeyboardInterrupt):
        print("\n👋 掰掰！")
        sys.exit(0)


def interactive_mode(theme: str = "slate", output_dir: str = None):
    from src.config import OUTPUT_DIR

    print("=" * 60)
    print("🪿 Anseropolis 互動模式 — 謠言查核教學")
    print("=" * 60)
    print("\n這個工具會帶你一步步完成謠言查核：")
    print("  1️⃣  貼上一段可疑訊息")
    print("  2️⃣  觀察語言指紋（有沒有「網傳」「快轉」等信號？）")
    print("  3️⃣  比對謠言庫（這則訊息有沒有被查核過？）")
    print("  4️⃣  AI 拆解聲明 + 搜尋證據")
    print("  5️⃣  結構化比對：NER / 數字 / 時間線")
    print("  6️⃣  可疑度評分 + 圖卡產出")

    # Step 1: Input
    text = _ask("請貼上你想查核的訊息（LINE 轉傳、社群貼文等）：")
    if not text:
        print("❌ 沒有輸入文字，結束。")
        return

    print(f"\n📝 收到！共 {len(text)} 字。")

    # Step 2: Student observes language fingerprints
    print("\n" + "─" * 40)
    print("🔎 第一步：觀察這段文字的語言特徵")
    print("   想想看：")
    print("   • 有沒有「網傳」「聽說」「消息人士」這類模糊來源？")
    print("   • 有沒有「快轉」「趕快分享」這類催促行動？")
    print("   • 有沒有「震驚」「真相」這類情緒詞？")
    guess_fingerprint = _ask("你觀察到什麼可疑特徵？（自由填寫）", "跳過")

    # Step 3: Ingest + Score (language fingerprints)
    _pause("讓 AI 掃描語言指紋…")
    print("\n⏳ 斷詞 + 語言指紋掃描…")
    from src.ingest import ingest, embed_text
    ingest_result = ingest(text)

    from src.score import score as compute_score, highlight_text, scan_phrases
    phrases = scan_phrases(text, ingest_result.get("ws"))
    if phrases:
        marked = highlight_text(text, phrases)
        print(f"\n🚨 偵測到的可疑語言指紋：")
        for p in phrases:
            print(f"   ⚡ [{p['label']}] 「{p['phrase']}」")
        print(f"\n   標記結果：{marked[:80]}")
    else:
        print("\n   ✅ 未偵測到明顯的謠言語言指紋")

    if guess_fingerprint != "跳過":
        print(f"\n   🔙 你的觀察：{guess_fingerprint}")
        print("   跟 AI 的結果比，你有沒有漏掉什麼？")

    # Step 4: Match rumor DB
    _pause("接下來比對謠言庫（4125 篇已查核報告）…")
    print("\n⏳ 比對中…")
    from src.match import match
    embedding = ingest_result.get("embedding")
    keywords = ingest_result.get("keywords", [])
    match_result = match(query_embedding=embedding, top_k=3, keywords=keywords)

    if match_result and match_result[0].get("similarity", 0) > 0.6:
        top = match_result[0]
        print(f"\n🎯 找到高度相似的已查核報告！")
        print(f"   相似度：{top['similarity']:.3f}")
        print(f"   判定：{top.get('verdict', '?')}")
        print(f"   標題：{top['title'][:60]}")
        print(f"   連結：{top.get('url', '')}")
    elif match_result:
        top = match_result[0]
        print(f"\n📋 最相似的報告（相似度偏低：{top['similarity']:.3f}）：")
        print(f"   {top['title'][:60]}")
        print("   → 可能是新謠言，或是已知謠言的變體")
    else:
        print("\n   📋 謠言庫中無相似報告，可能是新的")

    # Step 5: Decompose + Retrieve + Diff
    _pause("AI 拆解聲明 + 搜尋證據…")
    print("\n⏳ 拆解聲明…")
    from src.decompose import decompose
    decompose_result = {"claims": []}
    try:
        decompose_result = decompose(text)
        claims = decompose_result.get("claims", [])
        print(f"   → {len(claims)} 則聲明")
        for i, c in enumerate(claims, 1):
            print(f"   {i}. {c['text'][:50]}")
    except ConnectionError:
        claims = []
        print("   ⚠ LLM 不可用，跳過")

    retrieve_result = None
    if claims:
        print("\n⏳ 搜尋證據…")
        from src.retrieve import retrieve
        try:
            retrieve_result = retrieve(claims)
            for c in retrieve_result:
                v = c.get("assessment", {}).get("verdict", "?")
                print(f"   [{v}] {c['text'][:40]}")
        except Exception:
            print("   ⚠ 搜尋失敗")

    # Diff
    if retrieve_result:
        print("\n⏳ 結構化比對…")
        from src.diff import diff as run_diff
        try:
            retrieve_result = run_diff(retrieve_result)
            for c in retrieve_result:
                d = c.get("diff", {})
                for item in d.get("ner", []):
                    print(f"   🏷️  NER：「{item['claim_says']}」→「{item['evidence_says']}」")
                for item in d.get("numbers", []):
                    print(f"   🔢 數字：「{item['claim_says']}」→「{item['evidence_says']}」")
                for item in d.get("timeline", []):
                    print(f"   📅 時間：「{item['claim_says']}」→「{item['evidence_says']}」")
        except Exception:
            print("   ⚠ 比對失敗")

    # Step 6: Score + Render
    _pause("計算可疑度分數…")
    top_match = match_result[0] if match_result else None
    score_result = compute_score(
        text,
        tokens=ingest_result.get("ws"),
        match_result=top_match,
        claim_matches=claims if claims else None,
        retrieve_result=retrieve_result,
    )

    print(f"\n{'='*60}")
    print(f"📊 可疑度：{score_result['total']}/100 （{score_result['label']}）")
    print(f"{'='*60}")
    bd = score_result.get("breakdown", {})
    print(f"   語言指紋：{bd.get('linguistic', 0)}/40")
    print(f"   謠言庫相似：{bd.get('rumor_similarity', 0)}/25")
    print(f"   聲明比對：{bd.get('claim_match', 0)}/20")
    print(f"   證據反駁：{bd.get('verdict_refuted', 0)}/15")

    # Reflection
    print("\n" + "─" * 40)
    reflection = _ask("你的結論是什麼？這則訊息可信嗎？為什麼？", "跳過")

    # Package + Render
    print("\n⏳ 產生圖卡…")
    from src.package import package as make_pkg, save as save_pkg
    from src.render import render as render_card
    enrich_result = None  # skip in interactive for speed
    pkg = make_pkg(text, ingest_result, match_result, decompose_result, retrieve_result, enrich_result)
    pkg["score"] = score_result
    if reflection != "跳過":
        pkg["student_reflection"] = reflection
    save_pkg(pkg, output_dir or str(OUTPUT_DIR))

    if theme:
        try:
            card_path = render_card(pkg, theme=theme)
            print(f"   📸 {card_path}")
        except Exception as e:
            print(f"   ⚠ 圖卡失敗：{e}")

    print(f"\n{'='*60}")
    print("💡 思考題：")
    print("   • 這則訊息最大的問題是什麼？（來源不明？數字錯誤？時間嫁接？）")
    print("   • 如果有人傳給你，你會怎麼回覆？")
    print("   • 你覺得散播這則訊息的人，動機是什麼？")
    print("=" * 60)
