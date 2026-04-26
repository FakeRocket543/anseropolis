"""anseropolis.agent — Agent 模式：LLM 自主決定查核策略，pipeline 模組作為 skills"""

import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen, Request

# Fix imports when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import OUTPUT_DIR
from src.llm import chat as _chat

# ── Skills（每個 pipeline 模組包成一個 tool）──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ckip_segment",
            "description": "中文斷詞與實體提取。輸入一段中文，回傳斷詞結果、詞性、關鍵字。",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要斷詞的中文文字"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fingerprint_scan",
            "description": "掃描謠言語言指紋。檢查是否含有「網傳」「問號結尾」「引述」「情緒詞」等謠言特徵。",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_rumor_db",
            "description": "比對謠言庫。用 embedding 比對 TFC 4125 篇已知查核報告，找出最相似的。回傳標題、判定、URL、相似度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要比對的文字"},
                    "top_k": {"type": "integer", "description": "回傳前幾名", "default": 3},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜尋網頁。用關鍵字搜尋，回傳搜尋結果（標題、URL、摘要）。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜尋關鍵字"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "抓取網頁全文。輸入 URL，回傳網頁的文字內容（前 2000 字）。用於深入查證。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_package",
            "description": "打包題目包。將查核結果整理成 markdown 格式的題目包。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "題目包標題"},
                    "original_text": {"type": "string", "description": "原始謠言文字"},
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "evidence": {"type": "string"},
                                "source_url": {"type": "string"},
                                "status": {"type": "string", "enum": ["supported", "refuted", "insufficient"]},
                            },
                        },
                        "description": "聲明與證據列表",
                    },
                    "gaps": {"type": "array", "items": {"type": "string"}, "description": "還缺什麼"},
                    "notes": {"type": "string", "description": "查核者筆記"},
                },
                "required": ["title", "original_text", "claims"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是鵝改場（Anseropolis）的查核 agent。你的任務是查核一則可疑訊息。

你有以下工具可用：
- ckip_segment: 中文斷詞
- fingerprint_scan: 掃描謠言語言指紋
- match_rumor_db: 比對已知謠言庫（TFC 4125 篇）
- web_search: 搜尋網頁找證據
- fetch_url: 抓取特定網頁全文
- write_package: 打包最終題目包

查核流程建議（你可以自行調整順序）：
1. 先掃描語言指紋，判斷是否像謠言
2. 比對謠言庫，看有沒有已知的查核
3. 斷詞提取關鍵字
4. 用關鍵字搜尋證據
5. 如果需要，抓取特定網頁深入查證
6. 最後打包題目包

重要：不要判定「對/錯」，只呈現證據鏈。你是偵探，不是法官。"""


# ── Skill implementations ──

def _exec_ckip_segment(text: str) -> dict:
    from src.ingest import ckip_segment, extract_keywords
    r = ckip_segment(text)
    kws = extract_keywords(r["ws"], r["pos"])
    return {"ws": r["ws"][:20], "pos": r["pos"][:20], "keywords": kws}


def _exec_fingerprint(text: str) -> dict:
    from src.ingest import fingerprint
    return fingerprint(text)


def _exec_match(text: str, top_k: int = 3) -> list:
    from src.ingest import embed_text
    from src.match import match
    emb = embed_text(text)
    return match(emb, top_k=top_k)


def _exec_web_search(query: str) -> list:
    from src.retrieve import search
    return search(query)


def _exec_fetch_url(url: str) -> str:
    from urllib.request import urlopen, Request
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urlopen(req, timeout=15)
        import re as _re
        html = resp.read().decode("utf-8", errors="ignore")
        text = _re.sub(r'<[^>]+>', ' ', html)
        text = _re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception as e:
        return f"Error fetching {url}: {e}"


def _exec_write_package(title, original_text, claims, gaps=None, notes=None) -> str:
    status_map = {"supported": "✅", "refuted": "❌", "insufficient": "❓"}
    lines = [
        f"# 題目包：{title}\n",
        "## 原始訊息\n", original_text, "\n",
        "## 聲明拆解\n",
        "| # | 聲明 | 證據 | 來源 | 狀態 |",
        "|---|------|------|------|------|",
    ]
    for i, c in enumerate(claims):
        s = status_map.get(c.get("status", ""), "❓")
        lines.append(f'| {i+1} | {c["text"]} | {c.get("evidence","")} | {c.get("source_url","")} | {s} |')
    if gaps:
        lines.append("\n## 還缺什麼\n")
        for g in gaps:
            lines.append(f"- [ ] {g}")
    if notes:
        lines.append(f"\n## 查核者筆記\n\n{notes}")

    md = "\n".join(lines)
    OUTPUT_DIR.mkdir(exist_ok=True)
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"agent_{ts}.md"
    path.write_text(md)
    return f"題目包已存到 {path}"


SKILL_MAP = {
    "ckip_segment": lambda args: _exec_ckip_segment(args["text"]),
    "fingerprint_scan": lambda args: _exec_fingerprint(args["text"]),
    "match_rumor_db": lambda args: _exec_match(args["text"], args.get("top_k", 3)),
    "web_search": lambda args: _exec_web_search(args["query"]),
    "fetch_url": lambda args: _exec_fetch_url(args["url"]),
    "write_package": lambda args: _exec_write_package(**args),
}


# ── Agent loop ──


def run_agent(text: str, max_turns: int = 10, verbose: bool = True) -> str:
    """Run agent loop: LLM decides which tools to call."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"請查核以下訊息：\n\n{text}"},
    ]

    for turn in range(max_turns):
        if verbose:
            print(f"\n🪿 Turn {turn + 1}...")

        resp = _chat(messages, tools=TOOLS)
        choice = resp["choices"][0]
        msg = choice["message"]

        # Check if LLM wants to call tools
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # LLM is done, return final message
            final = msg.get("content", "")
            if verbose:
                print(f"📋 Agent 完成：\n{final[:200]}...")
            return final

        # Execute tool calls
        messages.append(msg)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]

            if verbose:
                print(f"  🔧 {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:60]})")

            skill = SKILL_MAP.get(fn_name)
            if skill:
                try:
                    result = skill(fn_args)
                    result_str = json.dumps(result, ensure_ascii=False, default=str)[:2000]
                except Exception as e:
                    result_str = f"Error: {e}"
            else:
                result_str = f"Unknown tool: {fn_name}"

            if verbose:
                print(f"    → {result_str[:100]}...")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{turn}"),
                "content": result_str,
            })

    return "Agent reached max turns without completing."


# ── Self-test ──

if __name__ == "__main__":
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"
    print(f"🪿 Anseropolis Agent Mode")
    print(f"📝 Input: {text}\n")
    result = run_agent(text, verbose=True)
    print(f"\n{'='*60}")
    print(result)
