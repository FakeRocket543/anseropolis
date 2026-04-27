# Anseropolis 🪿

> 台灣茶鵝實驗改良場 — Taiwan Tea Goose Experiment & Improvement Station
>
> 你想講話就補資料啊。

AI 備料 × 公民辯論 = 有證據的公共討論基礎設施。

## Quick Start

```bash
# 1. 啟動 LLM server
llama-server -m Ministral-3-3B-Instruct-2512-Q8_0.gguf -ngl 99 --port 8080 -c 4096 &

# 2. Pipeline 模式
python3 -m src.run "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"

# 3. 加圖卡
python3 -m src.run --theme emerald "網傳..."

# 4. 互動教學模式
python3 -m src.run --interactive

# 5. Agent 模式（LLM 自主決策）
python3 src/agent.py "網傳美國已正式宣布放棄台灣"

# 6. API server
python3 -m src.serve --port 9000
```

## Pipeline

```
ingest → match → decompose → retrieve → diff → score → package → render
  │        │        │           │         │       │        │         │
  CKIP    kNN     LLM       DuckDuckGo  LLM    詞典+    JSON+MD  Playwright
  embed   謠言庫   聲明拆解   證據檢索   NER/   多維     題目包   1080×1080
                                        數字/   加權
                                        時間線
```

## 使用方式

### CLI 模式
```bash
python -m src.run "網傳..."                    # 基本查核
python -m src.run --theme sky "網傳..."         # 加圖卡
python -m src.run --file input.txt --theme rose # 從檔案讀取
```

### 互動教學模式
```bash
python -m src.run --interactive
python -m src.run -i --theme violet
```

引導學生逐步完成：
1. 貼上可疑訊息
2. 觀察語言指紋（學生先自己找）
3. AI 掃描 + 比對謠言庫
4. 拆解聲明 + 搜尋證據
5. 結構化比對（NER/數字/時間線）
6. 可疑度分數拆解
7. 反思 + 圖卡產出

### 色系主題
```bash
--theme slate    # 深灰（預設）
--theme sky      # 天空藍
--theme emerald  # 翡翠綠
--theme amber    # 琥珀
--theme violet   # 紫
--theme rose     # 玫瑰
# 或任何 Tailwind CSS 色名
```

## Test Results

10/10 e2e tests passing. Average ~24s per fixture.

## Documentation

| 文件 | 內容 |
|------|------|
| [doc/GUIDE.md](doc/GUIDE.md) | 完整使用指南 |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) | 技術架構 |
| [doc/requirement.md](doc/requirement.md) | 需求書 |
| [doc/pipeline-design.md](doc/pipeline-design.md) | Pipeline 設計 |
| [doc/tea-goose-skill.md](doc/tea-goose-skill.md) | 教學用 skill 檔 |

## Related

| 專案 | 說明 |
|------|------|
| [Collatro](https://github.com/FakeRocket543/collatro) | 事實比對教學工具（初階版，無謠言庫） |

## License

MIT — 歡迎任何人使用，包括 TFC。
