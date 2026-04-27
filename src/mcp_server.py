"""anseropolis.mcp_server — MCP server for Gemini CLI / any MCP client.

Usage:
  python3 -m src.mcp_server

In Gemini CLI settings (~/.gemini/settings.json):
  {
    "mcpServers": {
      "anseropolis": {
        "command": "python3",
        "args": ["-m", "src.mcp_server"],
        "cwd": "/path/to/anseropolis"
      }
    }
  }
"""

import json
import sys


def _read_msg():
    """Read JSON-RPC message from stdin."""
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_msg(msg):
    """Write JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(id, result):
    _write_msg({"jsonrpc": "2.0", "id": id, "result": result})


def _error(id, code, message):
    _write_msg({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


# ── Tool definitions ──

TOOLS = [
    {
        "name": "fingerprint_scan",
        "description": "掃描謠言語言指紋。檢查是否含「網傳」「問號結尾」「引述」「情緒詞」等特徵。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要掃描的文字"}},
            "required": ["text"],
        },
    },
    {
        "name": "ckip_segment",
        "description": "中文斷詞+詞性標記+關鍵字提取。三層fallback：MLX CKIP → ckip-transformers → jieba。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要斷詞的中文"}},
            "required": ["text"],
        },
    },
    {
        "name": "match_rumor_db",
        "description": "比對TFC 4125篇謠言庫。用embedding或關鍵字找最相似的已知查核報告，回傳標題、判定、URL。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要比對的文字"},
                "top_k": {"type": "integer", "description": "回傳前幾名", "default": 3},
            },
            "required": ["text"],
        },
    },
    {
        "name": "enrich_entity",
        "description": "查詢Wikipedia/Wikidata實體背景。輸入實體名稱列表，回傳描述、分類、Wiki連結。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entities": {"type": "array", "items": {"type": "string"}, "description": "實體名稱列表"},
            },
            "required": ["entities"],
        },
    },
    {
        "name": "run_pipeline",
        "description": "執行完整查核pipeline（不含LLM步驟）。回傳半成品題目包：語言指紋+斷詞+實體背景+謠言庫比對。聲明拆解和證據搜尋由你（Gemini）完成。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要查核的可疑訊息"}},
            "required": ["text"],
        },
    },
    {
        "name": "write_package",
        "description": "將查核結果打包成題目包Markdown檔案。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "原始訊息"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "evidence": {"type": "string"},
                            "source_url": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    },
                    "description": "聲明與證據列表",
                },
                "notes": {"type": "string", "description": "查核者筆記"},
            },
            "required": ["text", "claims"],
        },
    },
]


# ── Tool implementations ──

def _exec_fingerprint(args):
    from src.ingest import fingerprint
    return fingerprint(args["text"])


def _exec_ckip(args):
    from src.ingest import ckip_segment, extract_keywords
    r = ckip_segment(args["text"])
    kws = extract_keywords(r["ws"], r["pos"], r.get("ws_search"))
    return {"ws": r["ws"][:30], "pos": r["pos"][:30], "keywords": kws}


def _exec_match(args):
    from src.ingest import embed_text
    from src.match import match
    emb = embed_text(args["text"])
    return match(query_embedding=emb, top_k=args.get("top_k", 3),
                 keywords=args["text"].split())


def _exec_enrich(args):
    from src.enrich import enrich
    return enrich(args["entities"])


def _exec_pipeline(args):
    import os
    os.environ["ANSEROPOLIS_LLM_URL"] = ""  # skip LLM steps
    from src.ingest import ingest
    from src.match import match
    from src.enrich import enrich

    ing = ingest(args["text"], compute_embedding=True)
    emb = ing.get("embedding")
    kws = ing.get("keywords", [])
    matches = match(query_embedding=emb, top_k=5, keywords=kws)

    entities = [w for w, p in zip(ing.get("ws", []), ing.get("pos", []))
                if p in ("Nb", "Nc") and len(w) >= 2][:5]
    enriched = enrich(entities) if entities else None

    return {
        "fingerprint": ing.get("fingerprint"),
        "keywords": kws,
        "matches": matches[:5],
        "entities": enriched,
        "note": "聲明拆解和證據搜尋請由你（Gemini）用 Google Search 完成",
    }


def _exec_write_package(args):
    from src.package import package, save, to_markdown
    from src.config import OUTPUT_DIR
    claims = [{"text": c["text"], "evidence": [{"snippet": c.get("evidence", "")}],
               "assessment": {"verdict": c.get("status", "insufficient")}}
              for c in args.get("claims", [])]
    pkg = package(args["text"], retrieve_result=claims)
    path = save(pkg, str(OUTPUT_DIR))
    return {"saved": str(path), "markdown": to_markdown(pkg)[:500]}


HANDLERS = {
    "fingerprint_scan": _exec_fingerprint,
    "ckip_segment": _exec_ckip,
    "match_rumor_db": _exec_match,
    "enrich_entity": _exec_enrich,
    "run_pipeline": _exec_pipeline,
    "write_package": _exec_write_package,
}


# ── MCP protocol loop ──

def main():
    # Server info
    sys.stderr.write("🪿 Anseropolis MCP server starting...\n")

    while True:
        msg = _read_msg()
        if msg is None:
            break

        method = msg.get("method", "")
        id = msg.get("id")

        if method == "initialize":
            _result(id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "anseropolis", "version": "0.1.0"},
            })

        elif method == "tools/list":
            _result(id, {"tools": TOOLS})

        elif method == "tools/call":
            name = msg.get("params", {}).get("name", "")
            arguments = msg.get("params", {}).get("arguments", {})
            handler = HANDLERS.get(name)
            if not handler:
                _error(id, -32601, f"Unknown tool: {name}")
                continue
            try:
                result = handler(arguments)
                _result(id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]})
            except Exception as e:
                _result(id, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})

        elif method == "notifications/initialized":
            pass  # client ack, ignore

        else:
            if id:
                _error(id, -32601, f"Unknown method: {method}")


if __name__ == "__main__":
    main()
