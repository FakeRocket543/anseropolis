# 鵝改場完整教學手冊

> Anseropolis — 台灣茶鵝實驗改良場
> 版本：0.1 ｜ 2026-04-26

---

## 目錄

1. [名詞解釋](#一名詞解釋)
2. [資料來源](#二資料來源)
3. [原理解釋](#三原理解釋)
4. [安裝與設定](#四安裝與設定)
5. [操作方法](#五操作方法)
6. [人要做的事](#六人要做的事)
7. [Skills 技能包](#七skills-技能包)
8. [互動方式](#八互動方式)
9. [題目包格式](#九題目包格式)
10. [教學場景](#十教學場景)
11. [FAQ](#十一faq)

---

## 一、名詞解釋

| 名詞 | 白話文 |
|------|--------|
| **Pipeline（管線）** | 一條固定的處理流水線。文字進去，題目包出來。每一步自動接下一步。 |
| **Agent（代理人）** | 讓 LLM 自己決定要用哪些工具、什麼順序來查核。比 pipeline 靈活但較慢。 |
| **Skill（技能）** | Pipeline 的每個模組包裝成 agent 可呼叫的工具。例如「斷詞」「比對謠言庫」「搜尋網頁」。 |
| **題目包** | Pipeline 的最終產出。包含原始訊息、語言指紋、實體背景、謠言庫比對、聲明拆解、證據、缺口分析。給人類接手用的。 |
| **聲明（Claim）** | 一段文字中可以被驗證真假的具體說法。「台灣去年交通事故增加 15%」是聲明，「交通很危險」是意見。 |
| **語言指紋** | 謠言的固定語言特徵。87% 的謠言含「網傳」，87% 含引述，81% 以問號結尾。用 regex 偵測。 |
| **embedding（嵌入向量）** | 把文字轉成一串數字（2048 維向量），語意相近的文字向量也相近。用來比對謠言庫。 |
| **kNN（k 近鄰）** | 在謠言庫的 4125 個向量中，找出跟新文字最相似的 k 個。用 cosine similarity 計算。 |
| **cosine similarity** | 兩個向量的夾角餘弦值。1.0 = 完全相同，0 = 無關，-1 = 完全相反。 |
| **match type** | 比對結果分三級：high（>0.85，幾乎同一則）、variant（0.6-0.85，可能是變體）、none（<0.6，新謠言）。 |
| **BM25 / TF-IDF** | 傳統的關鍵字權重演算法。用來在沒有 embedding 模型時做關鍵字比對（fallback）。 |
| **CKIP** | 中研院開發的中文斷詞系統。把「賴清德秘密帳戶曝光」切成「賴清德/秘密/帳戶/曝光」。 |
| **NER（命名實體辨識）** | 從文字中找出人名、機構名、地名。例如「賴清德」= PERSON，「民進黨」= ORG。 |
| **Wikipedia KG** | 維基百科的知識圖譜。查詢實體的分類、描述、Wikidata ID，自動標記領域。 |
| **Wikidata** | 維基百科的結構化資料庫。每個實體有 QID（如 Q57582 = 賴清德），包含職業、政黨、國籍等屬性。 |
| **llama-server** | llama.cpp 的 HTTP 伺服器。載入 GGUF 模型，提供 OpenAI 相容的 API。 |
| **SearXNG** | 自架的搜尋引擎聚合器。免費、無限查詢、保護隱私。Docker 一行啟動。 |
| **DuckDuckGo** | 預設的搜尋引擎 fallback。不需要 API key，但有速率限制。 |

---

## 二、資料來源

### 謠言庫

| 來源 | 筆數 | 內容 | 授權 |
|------|------|------|------|
| **台灣事實查核中心（TFC）** | 4,125 篇 | 標題、日期、判定、類目、URL、關鍵字、embedding | 非營利使用（依其著作權聲明） |
| **Cofacts 真的假的** | 待匯入 | LINE 群組回報的可疑訊息 + 群眾回覆 | MIT License（HuggingFace 公開） |
| **MyGoPen** | 待匯入 | 社群協作查核 | 待確認 |

### 本 repo 包含的資料

| 檔案 | 大小 | 內容 | 包含全文？ |
|------|------|------|-----------|
| `data/public_index.json` | 3.2 MB | 4125 篇 TFC 報告的 metadata | ❌ 只有標題、URL、關鍵字 |
| `data/report_embeddings.npz` | 28 MB | 4125 × 2048 報告級 embedding | ❌ 數學向量，無法還原原文 |
| `data/custom_dict.txt` | <1 KB | jieba 自訂詞典（26 詞） | N/A |
| `data/watchlist.json` | <1 KB | 定時爬蟲監控清單 | N/A |

### 即時查詢的外部來源

| 來源 | 用途 | 需要 API key？ |
|------|------|---------------|
| Wikipedia API | 實體背景查詢 | ❌ 免費 |
| Wikidata API | 結構化實體屬性 | ❌ 免費 |
| DuckDuckGo | 證據搜尋（fallback） | ❌ 免費 |
| SearXNG | 證據搜尋（自架） | ❌ 自架 |

---

## 三、原理解釋

### Pipeline 總覽

```
輸入文字
  │
  ▼
┌──────────┐  CKIP 斷詞 + Qwen3-VL embedding + regex 語言指紋
│ 1.ingest │  → 產出：斷詞結果、2048維向量、指紋命中、關鍵字
└────┬─────┘
     ▼
┌──────────┐  Wikipedia API + Wikidata API
│ 2.enrich │  → 產出：實體描述、分類、Wiki 連結
└────┬─────┘
     ▼
┌──────────┐  cosine similarity 比對 4125 篇 TFC 報告向量
│ 3.match  │  → 產出：最相似的報告、match type、URL
└────┬─────┘
     ▼
┌──────────┐  Gemma 4 E4B（本地 LLM）拆解可查核聲明
│4.decompose│ → 產出：聲明列表 [{text, difficulty}]
└────┬─────┘
     ▼
┌──────────┐  DuckDuckGo/SearXNG 搜尋 + LLM 評估證據
│5.retrieve│  → 產出：每個聲明的證據 + 支持/反駁/不足
└────┬─────┘
     ▼
┌──────────┐  彙整所有結果 → JSON + Markdown
│6.package │  → 產出：題目包（給人類接手）
└──────────┘
```

### 每一步的原理

**1. ingest（入料）**

三件事同時做：
- **CKIP 斷詞**：把中文切成詞，標記詞性（名詞/動詞/專有名詞）。三層 fallback：MLX CKIP → ckip-transformers → jieba。
- **embedding**：用 Qwen3-VL-Embedding-2B 把整段文字壓成 2048 個浮點數。語意相近的文字，向量也相近。
- **語言指紋**：用 regex 檢查是否含「網傳」「問號結尾」「引述」「情緒詞」「來源模糊」。這五個特徵覆蓋 87% 的已知謠言。

**2. enrich（實體背景）**

從斷詞結果中提取專有名詞（人名、機構名），查 Wikipedia API 拿到：
- 描述（「中華民國總統」）
- 分類（「2024年中華民國總統選舉候選人」）
- Wikidata 屬性（職業、政黨、國籍）
- Wikipedia 連結

這讓題目包自帶實體背景，人類不用自己查。

**3. match（謠言庫比對）**

把新文字的 embedding 跟 4125 篇 TFC 報告的 embedding 做 cosine similarity：
- **>0.85 = high**：幾乎確定是同一則謠言或極相似的變體
- **0.6-0.85 = variant**：可能是舊謠言翻新（換人名、換數字）
- **<0.6 = none**：新謠言，謠言庫裡沒有

如果沒有 embedding 模型，fallback 到關鍵字比對（用 public_index.json 裡的 claim_keywords）。

**4. decompose（聲明拆解）**

用本地 LLM（Gemma 4 E4B）把文字拆成可查核的原子聲明：
- 「賴清德秘密帳戶曝光，海外資產超過三十億」→ 拆成「賴清德有秘密帳戶」+「海外資產超過三十億」
- 意見不算聲明（「交通很危險」不可查核）
- 支援圖片視覺分析（透過 mmproj 多模態）

**5. retrieve（證據檢索）**

每個聲明用關鍵字搜尋網頁，找到相關結果後用 LLM 評估：
- **supported**：找到的證據支持這個聲明
- **refuted**：找到的證據反駁這個聲明
- **insufficient**：證據不足，需要人工查證

**6. package（打包）**

把以上所有結果組裝成題目包（JSON + Markdown），包含：原始訊息、語言指紋、實體背景、謠言庫比對、聲明×證據表格、缺口分析、查核者筆記欄位。

### Agent 模式的原理

Pipeline 是固定流程，Agent 是讓 LLM 自己決定：

```
LLM 拿到 6 個 skills（工具）：
  ckip_segment / fingerprint_scan / match_rumor_db /
  web_search / fetch_url / write_package

LLM 自己決定：
  「先掃指紋... 有『網傳』，查一下謠言庫... 命中了，
   看看 TFC 怎麼查的... 再搜一下國防部新聞稿...
   好，證據夠了，打包。」
```

Agent 可以跳步、重複、深入，比 pipeline 靈活但較慢。

---

## 四、安裝與設定

### 前置需求

| 項目 | 必要？ | 說明 |
|------|--------|------|
| Python 3.11+ | ✅ 必要 | `python3 --version` |
| numpy | ✅ 必要 | `pip install numpy` |
| jieba | ✅ 必要 | `pip install jieba`（CKIP 的最低 fallback） |
| llama-server | ✅ 必要 | `brew install llama.cpp` 或自行編譯 |
| Gemma 4 E4B Q8 GGUF | ✅ 必要 | 7.5 GB，聲明拆解 + 證據評估用 |
| mmproj GGUF | 選配 | 944 MB，圖片視覺分析用 |
| CKIP MLX 模型 | 選配 | ~800 MB，最佳斷詞品質 |
| ckip-transformers | 選配 | `pip install ckip-transformers`，次佳斷詞 |
| Qwen3-VL-Embedding-2B | 選配 | 4 GB，語意比對用。不設則用關鍵字比對 |
| SearXNG | 選配 | Docker 自架搜尋引擎。不設則用 DuckDuckGo |

### 安裝步驟

```bash
# 1. Clone
git clone https://github.com/xxx/anseropolis
cd anseropolis

# 2. 安裝依賴
pip install numpy jieba

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，至少填入 LLM 相關設定

# 4. 啟動 LLM server
llama-server \
  -m /path/to/gemma-4-e4b-it-Q8_0.gguf \
  --mmproj /path/to/mmproj-gemma-4-e4b-it-f16.gguf \
  -ngl 99 --port 8080 -c 4096 &

# 5. 驗證
curl http://localhost:8080/health
python3 src/match.py  # 測試謠言庫比對

# 6. 跑一次
python3 -m src.run "網傳美國已正式宣布放棄台灣"
```

### 環境變數一覽

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `ANSEROPOLIS_LLM_URL` | `http://localhost:8080/v1/chat/completions` | LLM API 端點 |
| `ANSEROPOLIS_LLM_MODEL` | `gemma4` | 模型名稱（任意填） |
| `ANSEROPOLIS_CKIP_DIR` | （空）| CKIP MLX 模型目錄 |
| `ANSEROPOLIS_CKIP_BATCH_PY` | （空）| ckip_batch.py 路徑 |
| `ANSEROPOLIS_EMBED_DIR` | （空）| Qwen3-VL-Embedding-2B 目錄 |
| `ANSEROPOLIS_SEARXNG_URL` | （空）| SearXNG URL |

不設選配項 = 自動降級：CKIP → jieba，embedding → 關鍵字比對，SearXNG → DuckDuckGo。

---

## 五、操作方法

### 方法 A：Pipeline CLI（推薦）

最穩定、最快（~25 秒/則）。

```bash
# 直接輸入文字
python3 -m src.run "網傳賴清德秘密帳戶曝光，海外資產超過三十億"

# 從檔案讀取
python3 -m src.run --file rumor.txt

# 指定輸出目錄
python3 -m src.run "網傳..." --output /path/to/output
```

輸出：
```
🪿 收到文字（21 字）
🪿 入料中… (CKIP + embedding)
🪿   斷詞完成，關鍵詞：賴清德 秘密 帳戶 曝光 海外
🪿 查詢實體背景… (Wikipedia)
🪿   找到 2 個實體：賴清德, 海外
🪿 比對謠言庫…
🪿   最佳比對：sim=0.7609 [variant] 【錯誤】網傳「賴清德823到金門…」
🪿 拆解聲明… (LLM)
🪿   拆出 1 則聲明
🪿 搜尋證據… (search + LLM)
🪿   [insufficient] 賴清德有秘密帳戶，且海外資產超過三十億
🪿 組裝題目包…
🪿 完成！耗時 31.1s → output/bc5052d1_20260426T234451.md
```

### 方法 B：Agent CLI（靈活）

LLM 自己決定查核策略（~30-60 秒/則）。

```bash
python3 src/agent.py "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"
```

輸出：
```
🪿 Turn 1: 🔧 fingerprint_scan → 偵測到「網傳」
🪿 Turn 2: 🔧 match_rumor_db  → 命中 TFC #137781 (sim 0.80)
🪿 Turn 3: 🔧 ckip_segment    → 提取關鍵字
🪿 Turn 4: 🔧 web_search      → 搜尋證據
🪿 Turn 5: 🔧 write_package   → 打包題目包
🪿 Turn 6: 📋 完成
```

### 方法 C：API Server（給外部串接）

```bash
# 啟動
python3 -m src.serve --port 9000

# Pipeline 模式
curl -X POST http://localhost:9000/api/check \
  -H "Content-Type: application/json" \
  -d '{"text": "網傳..."}'

# Agent 模式
curl -X POST http://localhost:9000/api/agent \
  -d '{"text": "網傳..."}'

# 列出題目包
curl http://localhost:9000/api/packages

# 取得特定題目包
curl http://localhost:9000/api/packages/bc5052d1
```

### 方法 D：定時爬蟲（Cron）

```bash
# 編輯監控清單
vim data/watchlist.json

# 手動跑一次
python3 -m src.intake_cron

# 設定 cron（每天凌晨 3 點）
crontab -e
0 3 * * * cd /path/to/anseropolis && python3 -m src.intake_cron >> /tmp/anseropolis.log 2>&1
```

### 方法 E：單步執行（除錯 / 教學）

```bash
# 只跑語言指紋
python3 -c "from src.ingest import fingerprint; print(fingerprint('網傳...'))"

# 只跑謠言庫比對
python3 -c "
from src.ingest import embed_text
from src.match import match
print(match(embed_text('美國放棄台灣'), top_k=3))
"

# 只跑聲明拆解
python3 -c "
from src.decompose import decompose
r = decompose('吃隔夜飯會產生大量黃麴毒素')
for c in r['claims']: print(c['text'])
"

# 只跑實體背景
python3 -c "
from src.enrich import enrich
r = enrich(['賴清德', '民進黨'])
for e in r['entities']:
    if e.get('found'): print(f'{e[\"name\"]}: {e[\"description\"]}')
"
```

---

## 六、人要做的事

Pipeline 自動做 80%，人做最後 20%。

### Pipeline 做的（自動）

| 步驟 | 做什麼 | 產出 |
|------|--------|------|
| 斷詞 | 切詞、提取關鍵字 | ws, pos, keywords |
| 實體背景 | 查 Wikipedia | 描述、分類、連結 |
| 謠言庫比對 | 找相似的已知查核 | match type, URL |
| 聲明拆解 | 找出可查核的事實 | claims list |
| 證據搜尋 | 搜尋 + 初步評估 | evidence + verdict |
| 打包 | 組裝題目包 | JSON + Markdown |

### 人要做的（手動）

| 步驟 | 做什麼 | 為什麼機器做不到 |
|------|--------|-----------------|
| **驗證連結** | 點開 pipeline 找到的證據連結，確認內容是否真的相關 | LLM 可能幻覺，連結可能失效 |
| **補充證據** | 打電話、查政府公報、問專家 | 需要人際互動和專業判斷 |
| **判斷灰色地帶** | 「部分正確」「脈絡誤導」這類需要人的判斷 | 不是二元對錯，需要理解脈絡 |
| **寫查核者筆記** | 在題目包的「查核者筆記」欄位寫下你的觀察 | 你的觀點是獨特的 |
| **決定是否發布** | 題目包品質夠了嗎？證據鏈完整嗎？ | 品質把關是人的責任 |

### 人不需要做的

- ❌ 不需要自己 Google 反搜圖（pipeline 會做）
- ❌ 不需要自己查 Wikipedia（enrich 會做）
- ❌ 不需要自己寫報告格式（package 會做）
- ❌ 不需要判定「對/錯」（鵝改場不蓋章）

---

## 七、Skills 技能包

Agent 模式下，LLM 可以呼叫以下 6 個 skills：

### 1. `ckip_segment`

| | |
|---|---|
| 功能 | 中文斷詞 + 詞性標記 + 關鍵字提取 |
| 輸入 | `{"text": "要斷詞的中文"}` |
| 輸出 | `{"ws": ["賴清德", "秘密", ...], "pos": ["Nb", "Na", ...], "keywords": ["賴清德", "秘密", ...]}` |
| 底層 | MLX CKIP → ckip-transformers → jieba（三層 fallback） |

### 2. `fingerprint_scan`

| | |
|---|---|
| 功能 | 掃描謠言語言指紋 |
| 輸入 | `{"text": "網傳..."}` |
| 輸出 | `{"網傳": true, "問號": false, "引述": false, "情緒詞": true, "來源模糊": false}` |
| 底層 | regex 比對 5 個特徵 |

### 3. `match_rumor_db`

| | |
|---|---|
| 功能 | 比對 TFC 4125 篇謠言庫 |
| 輸入 | `{"text": "要比對的文字", "top_k": 3}` |
| 輸出 | `[{"report_id": 137781, "similarity": 0.854, "title": "...", "verdict": "錯誤", "url": "...", "match_type": "high"}]` |
| 底層 | Qwen3-VL embedding → cosine kNN（或關鍵字 fallback） |

### 4. `web_search`

| | |
|---|---|
| 功能 | 搜尋網頁找證據 |
| 輸入 | `{"query": "搜尋關鍵字"}` |
| 輸出 | `[{"url": "...", "title": "...", "snippet": "..."}]` |
| 底層 | SearXNG（自架）→ DuckDuckGo（fallback） |

### 5. `fetch_url`

| | |
|---|---|
| 功能 | 抓取特定網頁全文（前 2000 字） |
| 輸入 | `{"url": "https://..."}` |
| 輸出 | 網頁文字內容（HTML 標籤已移除） |
| 底層 | urllib + regex strip HTML |

### 6. `write_package`

| | |
|---|---|
| 功能 | 打包查核結果為題目包 |
| 輸入 | `{"title": "...", "original_text": "...", "claims": [...], "gaps": [...], "notes": "..."}` |
| 輸出 | 題目包 Markdown 檔案路徑 |
| 底層 | 模板渲染 + 檔案寫入 |

### Skill 的使用場景

| 場景 | 用哪些 skills |
|------|-------------|
| 快速判斷是不是謠言 | fingerprint_scan + match_rumor_db |
| 完整查核 | 全部 6 個 |
| 只查實體背景 | ckip_segment（提取人名）→ 手動呼叫 enrich |
| 深入查證特定聲明 | web_search + fetch_url |

---

## 八、互動方式

### 方式 1：CLI 對話（你自己用）

```bash
# Pipeline 一行搞定
python3 -m src.run "貼上謠言"

# Agent 互動式
python3 src/agent.py "貼上謠言"
# → 看 agent 自己決定用哪些 skills
# → 最後產出題目包
```

### 方式 2：IDE + AI 助教（學生用）

```
學生在 IDE（kiro-cli / opencode）裡說：
  「讀 skills/tea-goose.md，帶我開始」

AI 助教會：
  1. 問學生：「貼上你看到的可疑訊息」
  2. 跑 pipeline 或引導手動流程
  3. 產出題目包
  4. 引導學生 review 三輪
  5. 學生交作業
```

### 方式 3：API 串接（外部系統）

```
Cofacts LINE Bot → POST /api/check → 回傳題目包 JSON
瀏覽器擴充 → POST /api/check → 顯示查核結果
其他查核機構 → GET /api/packages → 選題引用
```

### 方式 4：Cron 自動（無人值守）

```
cron 每天凌晨跑 → 爬蟲抓新謠言 → pipeline 自動產出題目包
你早上起來看 output/ 裡有什麼新的
挑有趣的 promote 到公開池
```

### 互動原則

1. **Pipeline 是保底**：穩定、可預測、適合批次
2. **Agent 是加分**：靈活、深入、適合單則深度查核
3. **人是最終決策者**：pipeline 和 agent 都只是備料，判斷是人的事
4. **不蓋章**：永遠不說「這是錯的」，只呈現證據鏈

---

## 九、題目包格式

完整的題目包 Markdown 長這樣：

```markdown
# 題目包：網傳賴清德秘密帳戶曝光，海外資產超過三十億

## 原始訊息
網傳賴清德秘密帳戶曝光，海外資產超過三十億

## 語言指紋
網傳
關鍵詞：賴清德 / 秘密 / 帳戶 / 曝光 / 海外 / 資產

## 實體背景
| 實體 | 說明 | Wikipedia 分類 | 來源 |
|------|------|---------------|------|
| 賴清德 | 中華民國總統 | 2024年中華民國總統選舉候選人 | [維基百科](link) |

## 謠言庫比對
- **[variant]** sim=0.7609 錯誤 — 【錯誤】網傳「賴清德823到金門…」
  https://tfc-taiwan.org.tw/...

## 聲明拆解
| # | 聲明 | 證據 | 來源 | 狀態 |
|---|------|------|------|------|
| 1 | 賴清德有秘密帳戶，海外資產超過三十億 | 5 筆 | web | ⚠️ insufficient |

## 還缺什麼
- 1 則聲明證據不足，需人工查證

## 查核者筆記
（待查核者填寫）
```

### 狀態說明

| 符號 | 意思 | 人要做什麼 |
|------|------|-----------|
| ✅ supported | 有證據支持此聲明 | 點開連結確認 |
| ❌ refuted | 有證據反駁此聲明 | 點開連結確認 |
| ⚠️ insufficient | 證據不足 | 需要人工查證（打電話、查公報） |
| ⏳ pending | 尚未檢索 | 等 pipeline 跑完或手動搜尋 |

---

## 十、教學場景

### W10 課堂流程（50 分鐘）

| 時間 | 做什麼 | 工具 |
|------|--------|------|
| 0-5 min | 開場：展示 TFC 數據（82% 錯誤率、人均 1.7 篇/月） | 投影片 |
| 5-10 min | 學生選一則可疑訊息 | LINE / FB / Cofacts |
| 10-20 min | 跑 pipeline 或手動流程 | `python3 -m src.run` 或 AI 助教 |
| 20-30 min | 討論證據：AI 找的連結你點開了嗎？ | 題目包 |
| 30-40 min | 改三輪：事實錯誤 → 遺漏 → 語氣 | IDE |
| 40-45 min | 亮 logo，講鵝改場的故事 | 投影片 |
| 45-50 min | 交作業 | |

### 學生作業

繳交：
1. 題目包（Markdown）
2. requirement.md（自己寫的需求）
3. （選做）自己組裝的 prompt

### 評分

| 層級 | 分數帶 | 看什麼 |
|------|--------|--------|
| 有做 | 60-70 | 題目包交了，有跑 pipeline |
| 有想 | 70-85 | AI 給的連結你有點開確認；有自己的觀察 |
| 有長出來 | 85-100 | 改了 prompt 說得出為什麼；發現 pipeline 的盲點 |

---

## 十一、FAQ

**Q: 需要 GPU 嗎？**
A: Apple Silicon 的 MPS 就夠。M1 16GB 以上可跑全部模型。

**Q: 沒有 Apple Silicon 怎麼辦？**
A: llama-server 支援 CPU 模式（較慢）。CKIP 用 ckip-transformers 或 jieba。embedding 不設就用關鍵字比對。

**Q: 需要網路嗎？**
A: ingest + match + decompose 不需要（全本地）。enrich 和 retrieve 需要（查 Wikipedia + 搜尋證據）。

**Q: 跑一則要多久？**
A: Pipeline ~25 秒，Agent ~30-60 秒。主要時間花在 LLM 推論。

**Q: 謠言庫多大？**
A: 31 MB（4125 篇 TFC 報告的標題 + embedding）。不含原文。

**Q: 可以加入其他查核機構的資料嗎？**
A: 可以。embed 後合併到 report_embeddings.npz，metadata 加到 public_index.json。

**Q: 為什麼不判定對錯？**
A: 事實查核不可能中立。鵝改場提供證據鏈，讓人自己判斷。

**Q: 為什麼叫鵝改場？**
A: 查核（chá hé）≈ 茶鵝（chá é）。仿農委會茶業改良場。Logo 是兩隻穿 guayabera 的鵝在吵架。精神：你想講話就補資料啊。

**Q: 授權？**
A: MIT。歡迎任何人使用，包括 TFC。

**Q: 我想貢獻程式碼？**
A: PR 歡迎。有問題開 Issue。全部不爽就 Fork。
