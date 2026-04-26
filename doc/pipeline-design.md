# Anseropolis Pipeline 設計

---

## 總覽

```
輸入（文字/URL/圖片）
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│  ingest  │───▶│  match   │───▶│ decompose│
│  入料     │    │  比對     │    │  拆解     │
└──────────┘    └──────────┘    └──────────┘
                     │                │
                     │ 命中            │ 未命中/變體
                     ▼                ▼
               ┌──────────┐    ┌──────────┐
               │ reference│    │ retrieve │
               │ 引入參考   │    │ 證據檢索  │
               └──────────┘    └──────────┘
                     │                │
                     ▼                ▼
               ┌─────────────────────────┐
               │        package          │
               │   打包題目包（diff 用）    │
               └─────────────────────────┘
                          │
                          ▼
                    人類 diff → merge → commit
```

---

## 模組設計

每個模組：吃 JSON，吐 JSON，獨立可測試。

### 1. ingest — 入料

```
輸入：文字 / URL / 圖片
輸出：ingest.json

{
  "id": "20260426_001",
  "raw_text": "網傳美國宣布放棄台灣...",
  "source_url": "https://...",       // optional
  "source_platform": "line",         // optional
  "images": ["path/to/img.png"],     // optional
  "timestamp": "2026-04-26T13:00:00"
}
```

做的事：
- URL → Playwright 抓全文
- 圖片 → OCR 提取文字（如有）
- 正規化：全形→半形、簡體→繁體（OpenCC）

### 2. match — 比對已知謠言庫

```
輸入：ingest.json
輸出：match.json

{
  "id": "20260426_001",
  "ckip": { "ws": [...], "pos": [...], "ner": [...] },
  "embedding": [0.12, -0.03, ...],   // 2048-dim
  "keywords": ["美國", "放棄", "台灣"],
  "fingerprint": { "網傳": true, "問號": false, "引述": true, "情緒詞": false },
  "matches": [
    {
      "source": "tfc",
      "id": "140904",
      "title": "謠言曲解川普談話...",
      "similarity": 0.87,
      "ngram_overlap": 0.45,
      "verdict": "錯誤",
      "match_type": "high"          // high / variant / none
    },
    {
      "source": "cofacts",
      "id": "abc123",
      "similarity": 0.72,
      "ngram_overlap": 0.31,
      "match_type": "variant"
    }
  ],
  "hash_hit": false                  // 完全重複
}
```

做的事：
1. CKIP ws/pos/ner
2. Qwen3-VL embedding
3. hash table 比對（完全重複 → 秒殺）
4. embedding cosine 比對謠言庫（TFC + Cofacts + MyGoPen）
5. n-gram overlap 計算（句法相似度）
6. 語言指紋 regex 掃描
7. 分類：
   - `hash_hit` = true → 完全重複，直接引入參考，跳過後續
   - `match_type: high`（cosine > 0.85 AND ngram > 0.4）→ 引入參考
   - `match_type: variant`（cosine 0.6-0.85）→ 引入參考 + 標記差異
   - `match_type: none`（cosine < 0.6）→ 新謠言，走完整 pipeline

### 3. decompose — 聲明拆解

```
輸入：match.json
輸出：claims.json

{
  "id": "20260426_001",
  "claims": [
    {
      "idx": 0,
      "text": "美國宣布放棄台灣",
      "type": "factual",            // factual / opinion / ambiguous
      "difficulty": "medium",
      "keywords": ["美國", "放棄", "台灣"],
      "search_suggestions": ["美國對台政策 2026", "台灣關係法"]
    },
    {
      "idx": 1,
      "text": "川普說台灣就是中國的",
      "type": "factual",
      "difficulty": "easy",
      "keywords": ["川普", "台灣", "中國"],
      "search_suggestions": ["Trump Taiwan China statement 2026"]
    }
  ]
}
```

做的事：
- 本地 LLM（Hermes/Gemma）拆解原文為原子聲明
- 每個聲明標記：可查核/意見/模糊
- 提取搜尋關鍵字
- 如果 match 階段有 high/variant，把已知查核結果的聲明也帶進來做比對基準

### 4. retrieve — 證據檢索

```
輸入：claims.json
輸出：evidence.json

{
  "id": "20260426_001",
  "claims": [
    {
      "idx": 0,
      "text": "美國宣布放棄台灣",
      "evidence": [
        {
          "url": "https://www.state.gov/...",
          "title": "U.S.-Taiwan Relations",
          "snippet": "The United States maintains...",
          "source_type": "government",
          "retrieved_by": "searxng"
        },
        {
          "url": "https://...",
          "title": "...",
          "snippet": "...",
          "source_type": "news",
          "retrieved_by": "playwright"    // 深層來源
        }
      ],
      "agent_assessment": "❌ 有證據反駁",
      "confidence": 0.82
    }
  ]
}
```

做的事：
1. 每個聲明的關鍵字 → SearXNG 搜尋
2. 淺層來源：直接抓 snippet
3. 深層來源：Playwright 進去抓全文（JS 渲染、PDF、需要滾動的頁面）
4. 公開資料 API：政府公報、立院議事錄、主計處
5. 反搜圖（如有圖片）：Google Lens via Playwright
6. 本地 LLM 比對證據與聲明，給出預判 + 信心分數
7. 如果 match 階段有參考資料，一併帶入做交叉比對

### 5. reference — 引入參考（match 命中時）

```
輸入：match.json（matches 欄位）
輸出：reference.json

{
  "id": "20260426_001",
  "references": [
    {
      "source": "tfc",
      "id": "140904",
      "url": "https://tfc-taiwan.org.tw/...",
      "title": "謠言曲解川普談話...",
      "verdict": "錯誤",
      "summary": "...",
      "match_type": "high",
      "diff_notes": null              // high match 無差異
    },
    {
      "source": "cofacts",
      "id": "abc123",
      "match_type": "variant",
      "diff_notes": "原版提到川普，此版改為拜登；數字從 66 架改為 100 架"
    }
  ]
}
```

做的事：
- 從謠言庫拉出完整查核結果
- variant 的話，LLM 比對差異，標記哪裡被改了
- 這步不做判斷，只是把「前科紀錄」整理好

### 6. package — 打包題目包

```
輸入：evidence.json + reference.json（如有）
輸出：package.json + package.md

{
  "id": "20260426_001",
  "raw_text": "...",
  "fingerprint": { ... },
  "references": [ ... ],             // 已知查核（如有）
  "claims": [
    {
      "text": "...",
      "evidence": [ ... ],
      "agent_assessment": "...",
      "confidence": 0.82,
      "status": "❌ / ✅ / ❓"
    }
  ],
  "gaps": [                           // 還缺什麼
    "需確認美國國務院 2026 年最新聲明",
    "建議致電外交部發言人"
  ],
  "metadata": {
    "auto_coverage": 0.67,            // 自動覆蓋率（2/3 聲明有證據）
    "has_reference": true,
    "difficulty": "medium",
    "created_at": "2026-04-26T13:05:00"
  }
}
```

做的事：
- 彙整所有上游產出
- 計算自動覆蓋率
- 生成 markdown 版題目包（給人讀）
- 生成 JSON 版（給 API / 前端）
- 列出缺口和建議查證方向

---

## 謠言庫（match 用）

```
anseropolis/data/
├── rumor_db.sqlite          ← 主資料庫
│   ├── rumors               ← text + embedding + ws + hash
│   ├── fact_checks          ← 已知查核結果
│   └── ngrams               ← 預計算的 n-gram index
│
├── embeddings/
│   ├── tfc_4125.npz         ← TFC embedding（已有）
│   ├── cofacts.npz          ← Cofacts embedding（待做）
│   └── mygopen.npz          ← MyGoPen embedding（待做）
│
└── stopwords/               ← 從 tfc-audit 複製
```

初始化：
```bash
# 從 tfc-audit 匯入
anseropolis db import --source tfc --parquet /path/to/sentences.parquet --embeddings /path/to/npz

# 從 Cofacts HuggingFace 匯入
anseropolis db import --source cofacts --hf Cofacts/line-msg-fact-check-tw
```

---

## 執行方式

```bash
# 單步
anseropolis ingest --url "https://..."
anseropolis match ingest.json
anseropolis decompose match.json
anseropolis retrieve claims.json
anseropolis package evidence.json

# 全自動（一行）
anseropolis run "網傳美國宣布放棄台灣..."
anseropolis run --url "https://facebook.com/..."

# API server
anseropolis serve --port 8000

# 定時爬蟲
anseropolis intake crawl --cron "0 3 * * *"

# 匯入謠言庫
anseropolis db import --source tfc ...
anseropolis db import --source cofacts ...
anseropolis db stats
```

---

## 依賴

| 模組 | 依賴 | 本地/雲端 |
|------|------|----------|
| ingest | Playwright, OpenCC | 本地 |
| match | CKIP (MLX), Qwen3-VL-Embed-2B, SQLite-vec | 本地 |
| decompose | Gemma 4 E4B 或其他 llama.cpp 相容模型 | 本地 |
| retrieve | SearXNG (Docker), Playwright | 本地 |
| reference | SQLite | 本地 |
| package | — | 本地 |
| api | FastAPI / Litestar | 本地 |

零雲端 API 費用。
