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

## Quick Start

```bash
git clone https://github.com/FakeRocket543/anseropolis.git
cd anseropolis
python3 setup.py          # 一鍵安裝
python3 -m src.run -i     # 互動教學模式
```

或直接跑：
```bash
python3 -m src.run --theme emerald "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"
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
2. **match 在 decompose 之前** — 如果謠言庫已經有完全相同的東西（sim > 0.9），可以直接回傳結果，不用浪費 LLM 時間。
3. **decompose 在 retrieve 之前** — 拆成原子聲明後，每個聲明獨立搜尋，precision 比整段文字搜尋高很多。
4. **diff 在 score 之前** — diff 的結果（有幾項不一致）是 score 的輸入之一。
5. **score 在 package 之前** — 分數是題目包的一部分。
6. **render 最後** — 需要所有資訊都就緒才能畫卡片。

---

## 模組詳解

### `src/config.py` — 設定中心
```python
LLM_URL, LLM_MODEL, CKIP_MODEL_DIR, EMBED_MODEL_DIR
```
全部環境變數驅動。**為什麼？** 因為每台機器的模型路徑不同，不能硬編碼。

### `src/llm.py` — LLM 推論（三層 fallback）
```
Tier 1: mlx-lm (in-process)
Tier 2: llama-server subprocess (自動啟動/關閉)
Tier 3: 外部 server
```
**為什麼三層？** 學生環境不一致。有 Apple Silicon 的用 mlx-lm（最快），沒有的連老師 server。中間層是給有 GGUF 檔但不想手動開 server 的人。

**為什麼支援 tool calling？** Agent 模式需要 function calling 讓 LLM 自主決定用哪個工具。

### `src/ingest.py` — 入料（斷詞 + embedding + 指紋）
```
輸入：文字
輸出：{ws, pos, keywords, embedding, fingerprint}
```
**三層 fallback：MLX CKIP → ckip-transformers → jieba**

**為什麼要斷詞？**
- 中文沒有空格，不斷詞就不能做 n-gram 指紋比對
- 詞性標記（Nb=人名, Nc=機構）用來提取實體

**為什麼要 embedding？**
- 謠言庫比對用 cosine similarity，需要向量表示
- 用 Qwen3-VL-Embedding-2B（2048 維），中文效果好

**為什麼要語言指紋？**
- 快速篩選：有「網傳」「快轉」的文字，不用跑完整 pipeline 就知道可疑
- 成本為零：純正則 + 詞典比對，不需要 LLM

### `src/match.py` — 謠言庫比對
```
輸入：embedding + keywords
輸出：[{report_id, title, url, similarity, match_type, verdict}]
```
**為什麼用 embedding kNN 而不是全文搜尋？**
- 謠言會換詞：「美國放棄台灣」→「美國拋棄台灣」→「美國不管台灣了」
- 全文搜尋抓不到這些變體，但 embedding 空間裡它們很近

**為什麼還要 keyword 比對？**
- embedding 模型可能沒裝（選配依賴），keyword 是 fallback
- 有些情況 keyword overlap 比 embedding 更精確（專有名詞完全相同）

### `src/decompose.py` — 聲明拆解
```
輸入：文字
輸出：{claims: [{text, keywords, search_suggestions, difficulty}]}
```
**為什麼用 LLM？** 同 Collatro — 自然語言的聲明邊界無法用規則切割。

**為什麼要 difficulty 欄位？** 讓 package 步驟知道哪些聲明需要人工介入（高難度 = 需要專家判斷）。

### `src/retrieve.py` — 證據檢索（含引擎路由）
```
輸入：claims + enrich_result
輸出：claims + evidence + assessment
```
**為什麼有引擎路由？**
```python
DOMAIN_ENGINES = {
    "medical": "google news,pubmed,google scholar",
    "military": "google news,bing news,brave.news",
    "china": "google news,sogou wechat,baidu",
}
```
不同領域的最佳搜尋引擎不同。醫學謠言要查 PubMed，軍事謠言要查新聞，中國相關要查百度/搜狗。enrich 步驟的 Wikipedia 分類告訴我們這則謠言屬於哪個領域。

**為什麼 SearXNG → DuckDuckGo fallback？**
- SearXNG 可以指定引擎，但需要自架
- DuckDuckGo 免費免 key，但不能指定引擎
- 教學環境通常沒有 SearXNG，所以 DDG 是 fallback

### `src/diff.py` — 結構化比對（新增）
```
輸入：claims + evidence
輸出：claims + diff（{ner, numbers, timeline, verdict, summary}）
```
**為什麼 Anseropolis 原本沒有這個？**
- 原本只有 `assessment.verdict`（supported/refuted/insufficient），是 LLM 的整體判斷
- 但教學需要「具體哪裡不一致」，所以加了結構化 diff
- 現在兩者並存：assessment 是整體判斷，diff 是細節

### `src/score.py` — 可疑度評分
```
輸入：text, tokens, match_result, claim_matches, retrieve_result
輸出：{total: 0-100, level, label, breakdown, phrases, tao}
```
**四維加權：**
| 維度 | 滿分 | 來源 |
|------|------|------|
| 語言指紋 | 40 | suspect_lexicon.yaml 詞典比對 |
| 謠言庫相似度 | 25 | match 步驟的 cosine similarity |
| 聲明比對率 | 20 | 有多少聲明在謠言庫找到高相似 |
| 證據反駁率 | 15 | retrieve 步驟判定 refuted 的比例 |

**為什麼語言指紋佔最多（40）？** 因為它是最可靠的信號。「網傳」「快轉」「震驚」這些詞幾乎只出現在謠言中，false positive 極低。

**為什麼不是 0 或 100？** 因為事實查核不是二元的。30 分代表「有一點可疑但不確定」，這比硬分類更誠實。

**國台辦偵測（tao_lexicon.yaml）：**
- 獨立軸，不計入總分
- 偵測統戰話術（「台獨」「分裂」「同胞」「統一」等）
- 為什麼獨立？因為統戰話術不一定是「假的」，但值得標記

### `src/enrich.py` — Wikipedia + Wikidata 實體查詢
```
輸入：實體名稱列表
輸出：{entities: [{name, description, categories, wikidata}], all_categories}
```
**為什麼查 Wikidata？**
- P31 (instance_of)：知道「台積電」是公司、「賴清德」是政治人物
- P17 (country)：知道實體屬於哪個國家 → 影響搜尋引擎路由
- P102 (party)：知道政治人物的黨派 → 幫助理解語境

### `src/package.py` — 題目包打包
```
輸出：JSON + Markdown
```
**為什麼叫「題目包」？** 設計理念是：機器產出的不是「答案」，是「題目」— 給公民記者認養查核的素材。

### `src/render.py` — 圖卡渲染
```
Tailwind HTML → Playwright → 1080×1080 PNG
```
**為什麼 Tailwind + Playwright？** 同 Collatro — 中文排版好、改色系容易、品質等同瀏覽器。

**圖卡內容：** 可疑度分數 + 指紋詞標記 + 謠言庫比對 + 聲明判定 + 結構化 diff

### `src/interactive.py` — 互動教學模式
```
流程：輸入 → 觀察指紋（學生先自己找）→ AI 掃描 → 謠言庫 → 拆解 → 搜尋 → diff → 分數 → 反思
```
**為什麼讓學生先觀察再看 AI 結果？** POE 教學法。學生先形成假設，再驗證，學習效果最好。

### `src/agent.py` — Agent 模式
```
LLM 拿到 6 個 skills（tools），自主決定查核策略
```
**為什麼要 Agent 模式？** Pipeline 是固定流程，但有些情況需要靈活：
- 圖片謠言需要先做 OCR
- 某些聲明需要深入搜尋（多輪）
- 有些明顯的謠言不需要跑完整 pipeline

### `src/serve.py` — HTTP API
### `src/intake_cron.py` — 定時爬蟲

---

## 依賴說明

| 套件 | 用途 | 為什麼選它 | 必要？ |
|------|------|-----------|--------|
| `mlx-lm` | 本地 LLM | Apple Silicon 原生，純 pip | 選配（可連外部 server） |
| `playwright` | HTML → PNG | 中文排版好 | 選配（不產圖卡就不需要） |
| `numpy` | embedding 運算 | cosine similarity 計算 | 必要 |
| `jieba` | 中文斷詞 fallback | 輕量、免模型下載 | 必要 |
| `pyyaml` | 讀取詞典 | suspect_lexicon.yaml | 必要 |
| `ckip-transformers` | 精確中文斷詞 | 學術級 NER | 選配（fallback 到 jieba） |
| `sentence-transformers` | embedding 模型 | Qwen3 embedding | 選配（fallback 到 keyword） |

**設計原則：核心功能（ingest + match + score）只需要 numpy + jieba + pyyaml。LLM 和圖卡是選配。**

---

## 色系主題

```bash
--theme slate | sky | emerald | amber | violet | rose
# 或任何 Tailwind CSS 色名
```

---

## 互動教學模式

```bash
python3 -m src.run --interactive
python3 -m src.run -i --theme violet
```

引導學生逐步完成：
1. 貼上可疑訊息
2. 自己觀察語言特徵（先猜再看）
3. AI 掃描語言指紋
4. 比對謠言庫（4125 篇）
5. 拆解聲明 + 搜尋證據
6. 結構化比對（NER/數字/時間線）
7. 可疑度分數拆解（四維度）
8. 反思 + 圖卡產出

---

## 與其他工具的比較

### 台灣現有工具

| 工具 | 做法 | 我們學到什麼 |
|------|------|-------------|
| **Cofacts 真的假的** | LINE bot + 群眾協作 | 群眾力量有效，但受限於「已知謠言」資料庫 |
| **MyGoPen / 美玉姨** | LINE bot + 編輯/串接 | 長輩友善的介面很重要，但人力是瓶頸 |
| **TFC** | 記者手動查核 | 品質高但產量低、選題有偏差、無法規模化 |

### 國際開源 pipeline

| 工具 | 架構 | 與 Anseropolis 的差異 |
|------|------|----------------------|
| **Loki** (1.1k⭐) | decompose → worthiness → query → evidence → verify | 最像我們的 pipeline，但英文 only + 依賴 OpenAI API |
| **SAFE** (Google) | 拆聲明 → Google Search → LLM 判定 | 閉源；我們的 retrieve 做類似的事但用免費搜尋 |
| **ClaimBuster** | ML 判斷 check-worthiness | 只做第一步（值不值得查），我們做完整流程 |
| **OpenFactCheck** | 統一評估框架 | 評估工具，不是查核工具；可以用來測我們的準確度 |
| **Veracity** (2025) | LLM + 搜尋 + 透明度 | 理念相近（強調可解釋），但英文 only |

### Anseropolis 的獨特之處

| 能力 | Cofacts | Loki | SAFE | **Anseropolis** |
|------|---------|------|------|-----------------|
| 中文原生 | ✓ | ✗ | ✗ | ✓ |
| 零成本（無 API） | ✓ | ✗ | ✗ | ✓ |
| 本地推論 | ✗ | ✗ | ✗ | ✓ |
| 謠言庫比對 | ✓ (自建) | ✗ | ✗ | ✓ (TFC 4125篇) |
| 語言指紋偵測 | ✗ | ✗ | ✗ | ✓ |
| 國台辦敘事偵測 | ✗ | ✗ | ✗ | ✓ |
| 結構化 diff | ✗ | ✗ | ✗ | ✓ |
| 可疑度評分 | ✗ | ✗ | ✗ | ✓ (0-100) |
| 教學互動模式 | ✗ | ✗ | ✗ | ✓ |
| Agent 模式 | ✗ | ✗ | ✗ | ✓ |

**共同缺口（= 我們填補的）：**
1. 全部英文 → 我們做中文
2. 全依賴雲端 API → 我們全本地
3. 全自動判定 → 我們是「備料」，人做最終判斷
4. 無教學功能 → 我們有互動模式
5. 無認知作戰偵測 → 我們有國台辦詞典

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
