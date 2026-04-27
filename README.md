# Anseropolis 🪿

> 台灣茶鵝實驗改良場 — Taiwan Tea Goose Experiment & Improvement Station
>
> 你想講話就補資料啊。

AI 備料 × 公民辯論 = 有證據的公共討論基礎設施。

---

## 為什麼做這個？

台灣事實查核機構（TFC）的結構性問題：
- 4-5 名全職記者，人均月產 1.7 篇，82% 判「錯誤」= 只打軟目標
- 選題偏差 2.2 倍（保護綠營 vs 藍營）
- 系統性迴避灰色地帶（中共認知作戰、美國對台承諾）
- 壟斷 IFCN 認證 = 單一守門人無外部監督

**Anseropolis 不是取代 TFC，是讓 TFC 這種機構變得不必要。**

核心差異：機器備料 + 人工判斷，全流程公開，任何人可審計。

---

## 安裝

### 方法一：一鍵安裝（推薦）

```bash
git clone https://github.com/FakeRocket543/anseropolis.git
cd anseropolis
python3 setup.py
```

`setup.py` 會自動完成：
- 安裝 mlx-lm + playwright + numpy + jieba + pyyaml
- 安裝 chromium 瀏覽器引擎
- 安裝 ckip-transformers（選配，精確斷詞）
- 下載 Mistral 8B 模型（首次約 4.5GB）

### 方法二：手動安裝

```bash
git clone https://github.com/FakeRocket543/anseropolis.git
cd anseropolis

# 核心依賴
pip install mlx-lm playwright numpy jieba pyyaml
playwright install chromium

# 選配：精確中文斷詞
pip install ckip-transformers
```

### 方法三：沒有 Apple Silicon

```bash
pip install playwright numpy jieba pyyaml
playwright install chromium
export ANSEROPOLIS_LLM_URL=http://老師IP:8080/v1/chat/completions
```

LLM 步驟由老師的 server 處理。ingest/match/score 仍在本地跑。

### 系統需求

| 項目 | 最低 | 建議 |
|------|------|------|
| Python | 3.11 | 3.12 |
| macOS | 13.5 (Ventura) | 14+ (Sonoma) |
| RAM | 8GB（用 3B 模型） | 24GB（全模型載入） |
| 晶片 | Apple Silicon (M1+) | M2/M3 |
| 磁碟 | 10GB（模型 + 資料） | — |

---

## 使用方式

### 1. 互動教學模式（推薦給學生）

```bash
python3 -m src.run --interactive
python3 -m src.run -i --theme violet
```

互動流程：
```
1️⃣  貼上可疑訊息（LINE 轉傳、社群貼文）
2️⃣  自己觀察語言特徵（有沒有「網傳」「快轉」？）
3️⃣  AI 掃描語言指紋 → 跟你的觀察比較
4️⃣  比對謠言庫（4125 篇已查核報告）
5️⃣  AI 拆解聲明 + 搜尋證據
6️⃣  結構化比對（NER / 數字 / 時間線）
7️⃣  可疑度分數拆解（四維度）
8️⃣  反思 + 圖卡產出
```

### 2. CLI 模式（一行跑完）

```bash
# 基本查核（無圖卡）
python3 -m src.run "網傳美國已正式宣布放棄台灣"

# 加圖卡
python3 -m src.run --theme emerald "網傳..."

# 從檔案讀取
python3 -m src.run --file rumor.txt --theme sky
```

### 3. Agent 模式（LLM 自主決策）

```bash
python3 src/agent.py "網傳美國已正式宣布放棄台灣"
```

Agent 拿到 6 個工具（skills），自己決定查核策略。適合深度查核。

### 4. HTTP API

```bash
python3 -m src.serve --port 9000

# 另一個 terminal
curl -X POST http://localhost:9000/api/check \
  -H "Content-Type: application/json" \
  -d '{"text": "網傳..."}'
```

### 5. 色系主題

```bash
--theme slate    # 深灰（預設）
--theme sky      # 天空藍
--theme emerald  # 翡翠綠
--theme amber    # 琥珀
--theme violet   # 紫
--theme rose     # 玫瑰
# 或任何 Tailwind CSS 色名
```

---

## 產出

每次執行會產生：

```
output/
├── <slug>_<timestamp>.json    # 完整結果
├── <slug>_<timestamp>.md      # Markdown 題目包
└── <slug>_card.png            # 1080×1080 圖卡（有加 --theme 時）
```

---

## Pipeline 架構

```
ingest → match → decompose → retrieve → diff → score → package → render
  │        │        │           │         │       │        │         │
  CKIP    kNN     LLM       DuckDuckGo  LLM    詞典+    JSON+MD  Playwright
  embed   謠言庫   聲明拆解   證據檢索   NER/   多維     題目包   1080×1080
                                        數字/   加權
                                        時間線
```

### 為什麼是這個順序？

1. **ingest 最先** — 斷詞 + embedding 是所有後續步驟的基礎。沒有斷詞就不能做指紋掃描，沒有 embedding 就不能做謠言庫比對。
2. **match 在 decompose 之前** — 如果謠言庫已有完全相同的（sim > 0.9），可以直接回傳，不浪費 LLM 時間。
3. **decompose 在 retrieve 之前** — 拆成原子聲明後，每個獨立搜尋，precision 比整段搜尋高。
4. **retrieve 在 diff 之前** — 必須先有證據才能比對。
5. **diff 在 score 之前** — diff 結果是 score 的輸入之一。
6. **score 在 package 之前** — 分數是題目包的一部分。
7. **render 最後** — 需要所有資訊就緒才能畫卡片。

---

## 模組詳解

### `src/ingest.py` — 入料（斷詞 + embedding + 指紋）
```
輸入：文字
輸出：{ws, pos, keywords, embedding, fingerprint}
三層 fallback：MLX CKIP → ckip-transformers → jieba
```
**為什麼要斷詞？** 中文沒有空格。不斷詞就不能做 n-gram 指紋比對，也不能提取實體。

**為什麼要 embedding？** 謠言庫比對用 cosine similarity，需要向量。用 Qwen3-VL-Embedding-2B（2048 維）。

**為什麼要語言指紋？** 快速篩選：有「網傳」「快轉」的文字，不用跑完整 pipeline 就知道可疑。成本為零（純正則 + 詞典）。

### `src/match.py` — 謠言庫比對
```
輸入：embedding + keywords
輸出：[{report_id, title, url, similarity, match_type, verdict}]
```
**為什麼用 embedding kNN？** 謠言會換詞（「放棄台灣」→「拋棄台灣」→「不管台灣了」），全文搜尋抓不到，但 embedding 空間裡它們很近。

**為什麼還要 keyword 比對？** embedding 模型是選配依賴，keyword 是 fallback。

### `src/decompose.py` — 聲明拆解
```
輸入：文字
輸出：{claims: [{text, keywords, search_suggestions, difficulty}]}
```
**為什麼用 LLM？** 自然語言的聲明邊界無法用規則切割。

### `src/retrieve.py` — 證據檢索（含引擎路由）
```
輸入：claims + enrich_result
輸出：claims + evidence + assessment
```
**引擎路由：** 醫學謠言查 PubMed，軍事查新聞，中國相關查百度/搜狗。enrich 的 Wikipedia 分類告訴我們屬於哪個領域。

**SearXNG → DuckDuckGo fallback：** SearXNG 可指定引擎但需自架，DDG 免費免 key。

### `src/diff.py` — 結構化比對
```
輸入：claims + evidence
輸出：claims + diff（{ner, numbers, timeline, verdict, summary}）
```
**三個面向：** NER（張冠李戴）、數字（誇大縮小）、時間線（倒置嫁接）。覆蓋 80% 事實錯誤。

### `src/score.py` — 可疑度評分
```
輸出：{total: 0-100, level, label, breakdown, phrases, tao}
```
**四維加權：**
| 維度 | 滿分 | 來源 |
|------|------|------|
| 語言指紋 | 40 | suspect_lexicon.yaml |
| 謠言庫相似度 | 25 | match 的 cosine similarity |
| 聲明比對率 | 20 | 多少聲明在庫中找到高相似 |
| 證據反駁率 | 15 | retrieve 判定 refuted 的比例 |

**國台辦偵測（tao_lexicon.yaml）：** 獨立軸，不計入總分。偵測統戰話術（「台獨」「分裂」「同胞」）。獨立是因為統戰話術不一定「假」，但值得標記。

### `src/enrich.py` — Wikipedia + Wikidata 實體查詢
```
輸出：{entities, all_categories, wikidata_types}
```
**為什麼查 Wikidata？** P31(是什麼)、P17(國家)、P102(政黨) — 幫助理解語境和路由搜尋引擎。

### `src/package.py` — 題目包打包
**為什麼叫「題目包」？** 機器產出的不是「答案」，是「題目」— 給公民記者認養查核的素材。

### `src/render.py` — 圖卡渲染
**Tailwind + Playwright：** 中文排版好、改色系容易、品質等同瀏覽器。

### `src/interactive.py` — 互動教學模式
**POE 教學法：** 讓學生先觀察語言特徵（預測），再看 AI 結果（觀察），最後反思（解釋）。

### `src/agent.py` — Agent 模式
LLM 拿到 6 個 skills，自主決定查核策略。Pipeline 是固定流程，Agent 是靈活流程。

### `src/serve.py` — HTTP API
### `src/intake_cron.py` — 定時爬蟲

---

## 依賴說明

| 套件 | 用途 | 為什麼選它 | 必要？ |
|------|------|-----------|--------|
| `numpy` | embedding 運算 | cosine similarity | 必要 |
| `jieba` | 中文斷詞 fallback | 輕量、免模型 | 必要 |
| `pyyaml` | 讀取指紋詞典 | suspect_lexicon.yaml | 必要 |
| `mlx-lm` | 本地 LLM | Apple Silicon 原生 | 選配 |
| `playwright` | HTML → PNG | 中文排版好 | 選配 |
| `ckip-transformers` | 精確斷詞 + NER | 學術級 | 選配 |
| `sentence-transformers` | embedding | Qwen3 2048d | 選配 |

**設計原則：核心功能（ingest + match + score）只需要 numpy + jieba + pyyaml。LLM 和圖卡是選配。**

---

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `ANSEROPOLIS_LLM_URL` | `http://localhost:8080/v1/chat/completions` | LLM API |
| `ANSEROPOLIS_LLM_MODEL` | `ministral` | 模型名稱 |
| `ANSEROPOLIS_MLX_MODEL` | `mlx-community/Ministral-8B-Instruct-2412-4bit` | mlx-lm 模型 |
| `ANSEROPOLIS_GGUF` | （空） | GGUF 檔路徑 |
| `ANSEROPOLIS_CKIP_DIR` | （空） | MLX CKIP 模型目錄 |
| `ANSEROPOLIS_CKIP_BATCH_PY` | （空） | ckip_batch.py 路徑 |
| `ANSEROPOLIS_EMBED_DIR` | （空） | Qwen embedding 模型目錄 |
| `ANSEROPOLIS_SEARXNG_URL` | （空） | SearXNG 位址 |

---

## 與其他工具的比較

### 台灣現有工具

| 工具 | 做法 | 我們學到什麼 |
|------|------|-------------|
| **Cofacts 真的假的** | LINE bot + 群眾協作 | 群眾力量有效，但受限於「已知謠言」資料庫 |
| **MyGoPen / 美玉姨** | LINE bot + 編輯/串接 | 長輩友善介面重要，但人力是瓶頸 |
| **TFC** | 記者手動查核 | 品質高但產量低、選題有偏差、無法規模化 |

### 國際開源 pipeline

| 工具 | 架構 | 與 Anseropolis 的差異 |
|------|------|----------------------|
| **Loki** (1.1k⭐) | decompose → worthiness → query → evidence → verify | 最像我們，但英文 only + 依賴 OpenAI |
| **SAFE** (Google) | 拆聲明 → Google Search → LLM 判定 | 閉源；我們用免費搜尋 |
| **ClaimBuster** | ML 判斷 check-worthiness | 只做第一步，我們做完整流程 |
| **OpenFactCheck** | 統一評估框架 | 評估工具，不是查核工具 |

### Anseropolis 的獨特之處

| 能力 | Cofacts | Loki | **Anseropolis** |
|------|---------|------|-----------------|
| 中文原生 | ✓ | ✗ | ✓ |
| 零成本（無 API） | ✓ | ✗ | ✓ |
| 本地推論 | ✗ | ✗ | ✓ |
| 謠言庫比對 | ✓ (自建) | ✗ | ✓ (TFC 4125篇) |
| 語言指紋偵測 | ✗ | ✗ | ✓ |
| 國台辦敘事偵測 | ✗ | ✗ | ✓ |
| 結構化 diff | ✗ | ✗ | ✓ |
| 可疑度評分 | ✗ | ✗ | ✓ (0-100) |
| 教學互動模式 | ✗ | ✗ | ✓ |

---

## 與 Collatro 的關係

[Collatro](https://github.com/FakeRocket543/collatro) 是教學簡化版。

| | Collatro | Anseropolis |
|---|---|---|
| 核心問題 | 「這跟來源對不對得上？」 | 「這是不是謠言？」 |
| 需要的資料 | 無（即時搜尋） | 謠言庫 + 指紋詞典 |
| 判斷依據 | 聲明 vs 證據的差異 | 語言特徵 + 庫比對 + 證據 |
| 適合 | 初學者（學方法） | 進階（學偵測） |

**教學建議：先 Collatro 學「怎麼查」，再 Anseropolis 學「怎麼看出可疑」。**

---

## Documentation

| 文件 | 內容 |
|------|------|
| [doc/GUIDE.md](doc/GUIDE.md) | 完整使用指南 |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) | 技術架構圖 |
| [doc/requirement.md](doc/requirement.md) | 需求書（問題分析 + 競品比較） |
| [doc/pipeline-design.md](doc/pipeline-design.md) | 每個模組的 JSON schema |

---

## License

MIT — 歡迎任何人使用，包括 TFC。
