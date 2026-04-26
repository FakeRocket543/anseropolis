# 鵝改場使用指南

> Anseropolis — 台灣茶鵝實驗改良場
> 你想講話就補資料啊。

---

## 什麼是鵝改場

AI 備料 × 公民辯論的查核基礎設施。

Pipeline 自動處理一則可疑訊息：斷詞 → 比對謠言庫 → 拆解聲明 → 搜尋證據 → 打包題目包。不蓋章，不當法官，攤開證據讓人自己判斷。

---

## 安裝與設定

### 前置需求

| 項目 | 說明 |
|------|------|
| Python 3.11+ | `python3 --version` |
| llama-server | `brew install llama.cpp` 或自行編譯 |
| CKIP MLX 模型 | `（見 .env.example 設定）` |
| Qwen3-VL-Embedding-2B | 4GB，sentence-transformers 格式 |
| Gemma 4 E4B Q8 | 7.5GB GGUF + 944MB mmproj |

### 啟動 LLM Server

```bash
llama-server \
  -m /path/to/gemma-4-e4b-it-Q8_0.gguf \
  --mmproj /path/to/mmproj-gemma-4-e4b-it-f16.gguf \
  -ngl 99 --port 8080 -c 4096 &
```

驗證：

```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

### 驗證安裝

```bash
cd anseropolis

# 測試 match 模組（不需要 LLM）
python3 src/match.py

# 測試 decompose（需要 LLM server）
python3 -c "from src.decompose import decompose; print(decompose('測試'))"
```

---

## 使用方式

### 一、Pipeline 模式（推薦，穩定快速）

```bash
python3 -m src.run "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"
```

輸出：
```
🪿 Anseropolis Pipeline
📝 Input: 網傳美國已正式宣布放棄台灣...

⏳ ingest...
  fingerprint: 網傳✓ 問號✗ 引述✗ 情緒詞✗
  keywords: ['美國', '放棄', '台灣', '戰機', '扣留']

⏳ match...
  🎯 TFC #137781 (sim=0.854) 網傳美國扣留66架F-16不給台灣是錯誤訊息

⏳ decompose...
  📋 2 claims extracted

⏳ retrieve...
  🔍 searching evidence...

⏳ package...
💾 output/20260426_001.md
💾 output/20260426_001.json
```

產出的 `output/20260426_001.md` 就是題目包。

### 二、Agent 模式（靈活，LLM 自主決策）

```bash
python3 src/agent.py "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"
```

Agent 自己決定查核順序：
```
Turn 1: 🔧 fingerprint_scan → 偵測到「網傳」
Turn 2: 🔧 match_rumor_db  → 命中 TFC #137781
Turn 3: 🔧 ckip_segment    → 提取關鍵字
Turn 4: 🔧 web_search      → 搜尋證據
Turn 5: 🔧 write_package   → 打包題目包
```

### 三、API 模式（給外部串接）

```bash
python3 -m src.serve --port 9000
```

呼叫：

```bash
# Pipeline 模式
curl -X POST http://localhost:9000/api/check \
  -H "Content-Type: application/json" \
  -d '{"text": "網傳..."}'

# Agent 模式
curl -X POST http://localhost:9000/api/agent \
  -H "Content-Type: application/json" \
  -d '{"text": "網傳..."}'

# 列出題目包
curl http://localhost:9000/api/packages

# 取得特定題目包
curl http://localhost:9000/api/packages/20260426_001
```

### 四、定時爬蟲（cron）

編輯監控清單：

```bash
cat data/watchlist.json
```

```json
[
  {"type": "keyword", "value": "網傳", "source": "duckduckgo"},
  {"type": "keyword", "value": "瘋傳 台灣", "source": "duckduckgo"},
  {"type": "url", "value": "https://cofacts.tw/hoax-for-you", "source": "cofacts"}
]
```

手動跑一次：

```bash
python3 -m src.intake_cron
```

設定 cron：

```bash
crontab -e
# 每天凌晨 3 點
0 3 * * * cd /path/to/anseropolis && python3 -m src.intake_cron >> /tmp/anseropolis.log 2>&1
```

### 五、單步執行（除錯 / 教學）

```bash
# 語言指紋
python3 -c "
from src.ingest import fingerprint
print(fingerprint('網傳美國已正式宣布放棄台灣'))
"

# 謠言庫比對
python3 -c "
from src.ingest import embed_text
from src.match import match
results = match(embed_text('美國放棄台灣 F-16'), top_k=3)
for r in results:
    print(f'{r[\"similarity\"]:.3f} [{r[\"match_type\"]}] {r[\"title\"][:50]}')
"

# 聲明拆解
python3 -c "
from src.decompose import decompose
r = decompose('吃隔夜飯會產生大量黃麴毒素，嚴重致癌')
for c in r['claims']:
    print(f'[{c[\"difficulty\"]}] {c[\"text\"]}')
"
```

---

## Pipeline 架構

```
輸入（文字）
    │
    ▼
┌──────────┐
│  ingest  │  CKIP 斷詞 + Qwen3-VL embedding + 語言指紋 + 關鍵字
└────┬─────┘
     ▼
┌──────────┐
│  match   │  embedding kNN 比對 TFC 4125 篇謠言庫
└────┬─────┘  → high (>0.85) / variant (0.6-0.85) / none (<0.6)
     ▼
┌──────────┐
│ decompose│  Gemma 4 E4B 拆解可查核聲明（支援圖片視覺分析）
└────┬─────┘
     ▼
┌──────────┐
│ retrieve │  DuckDuckGo / SearXNG 搜尋 + LLM 評估證據
└────┬─────┘
     ▼
┌──────────┐
│ package  │  打包題目包（JSON + Markdown）
└──────────┘
     │
     ▼
  output/YYYYMMDD_NNN.md
  output/YYYYMMDD_NNN.json
```

### 每個模組的角色

| 模組 | 吃什麼 | 吐什麼 | 依賴 |
|------|--------|--------|------|
| ingest | 文字 | ws/pos + embedding + fingerprint + keywords | CKIP MLX, Qwen3-VL-2B |
| match | embedding | top-k 相似報告 + match_type | report_embeddings.npz (28MB) |
| decompose | 文字 [+ 圖片] | claims [{text, difficulty}] | llama-server (Gemma 4 E4B) |
| retrieve | claims | evidence [{url, title, snippet}] + assessment | DuckDuckGo / SearXNG |
| package | 以上全部 | 題目包 JSON + MD | — |
| agent | 文字 | 自主查核結果 | 以上全部作為 skills |

### 謠言庫比對原理

```
新文字 → Qwen3-VL embed → 2048 維向量
    ↓
cosine similarity 比對 4125 篇報告的向量
    ↓
similarity > 0.85 → high（幾乎確定是同一則）
similarity 0.6-0.85 → variant（可能是變體）
similarity < 0.6 → none（新謠言）
```

### 語言指紋偵測

從 TFC 4125 篇提取的謠言特徵：

| 特徵 | 謠言命中率 |
|------|-----------|
| 含「網傳」 | 87% |
| 含引述「…」 | 87% |
| 以「？」結尾 | 81% |
| 情緒詞 | 常見 |

---

## 題目包格式

```markdown
# 題目包：[謠言摘要]

## 原始訊息
[完整原文 + 來源]

## 語言指紋
- 網傳 ✓/✗ | 問號 ✓/✗ | 引述 ✓/✗ | 情緒詞 ✓/✗

## 謠言庫比對
- TFC #XXXXX (sim=0.XX) [標題](URL)

## 聲明拆解
| # | 聲明 | 證據 | 來源 | 狀態 |
|---|------|------|------|------|
| 1 | ... | ... | URL | ✅/❌/❓ |

## 還缺什麼
- [ ] 需要確認的事項

## 查核者筆記
[人類補充]
```

狀態說明：
- ✅ 有證據支持
- ❌ 有證據反駁
- ❓ 證據不足，需進一步查證

---

## 教學用法（W10 課堂）

### 準備

1. 確保 llama-server 在跑
2. 把 `doc/tea-goose-skill.md` 放進學生的 `skills/` 資料夾

### 課堂流程

```
學生在 IDE 裡說：「讀 skills/tea-goose.md，帶我開始」
    ↓
Agent 問：「貼上你看到的可疑訊息」
    ↓
學生貼文字
    ↓
python3 -m src.run "學生貼的文字"
    ↓
產出題目包 → 學生 review → 改三輪 → 交作業
```

### 如果沒有 pipeline 環境

學生可以手動走流程（見 tea-goose-skill.md）：
1. 語言指紋掃描（肉眼）
2. 拆解聲明（用 AI 助手）
3. 搜尋證據（Google）
4. 打包題目包（markdown）

---

## FAQ

**Q: 需要 GPU 嗎？**
A: Apple Silicon 的 MPS 就夠。M1 以上都能跑。

**Q: 需要網路嗎？**
A: ingest + match + decompose 不需要（全本地）。retrieve 需要（搜尋證據）。

**Q: 跑一則要多久？**
A: Pipeline 模式約 24 秒，Agent 模式約 30-60 秒。

**Q: 謠言庫多大？**
A: 31 MB（4125 篇 TFC 報告的標題 + embedding，不含原文）。

**Q: 可以加入 Cofacts 資料嗎？**
A: 可以。下載 HuggingFace 資料集，embed 後合併到 report_embeddings.npz。

**Q: 為什麼不判定對錯？**
A: 因為事實查核不可能中立。鵝改場提供證據鏈，讓人自己判斷。

**Q: 授權？**
A: MIT。歡迎任何人使用，包括 TFC。
