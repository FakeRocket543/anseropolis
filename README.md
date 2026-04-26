# Anseropolis 🪿

> 台灣茶鵝實驗改良場 — Taiwan Tea Goose Experiment & Improvement Station
>
> 你想講話就補資料啊。

AI 備料 × 公民辯論 = 有證據的公共討論基礎設施。

## Quick Start

```bash
# 1. 啟動 LLM server
llama-server -m gemma-4-e4b-it-Q8_0.gguf --mmproj mmproj-*.gguf -ngl 99 --port 8080 -c 4096 &

# 2. Pipeline 模式（穩定，~24s）
python3 -m src.run "網傳美國已正式宣布放棄台灣，F-16戰機全數扣留不交付"

# 3. Agent 模式（靈活，LLM 自主決策）
python3 src/agent.py "網傳美國已正式宣布放棄台灣"

# 4. API server
python3 -m src.serve --port 9000
curl -X POST http://localhost:9000/api/check -d '{"text": "網傳..."}'

# 5. 定時爬蟲
python3 -m src.intake_cron
```

## Pipeline

```
ingest → match → decompose → retrieve → package
  │        │        │           │          │
  CKIP    kNN     Gemma4    DuckDuckGo   JSON+MD
  embed   謠言庫   聲明拆解   證據檢索     題目包
```

## Test Results

10/10 e2e tests passing. Average ~24s per fixture.

## Documentation

| 文件 | 內容 |
|------|------|
| [doc/GUIDE.md](doc/GUIDE.md) | 完整使用指南（安裝、四種使用方式、教學用法、FAQ） |
| [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) | 技術架構（系統圖、模組依賴、資料流、模型） |
| [doc/requirement.md](doc/requirement.md) | 需求書（品牌定位、設計原則、MVP 規劃） |
| [doc/pipeline-design.md](doc/pipeline-design.md) | Pipeline 設計（每個模組的 JSON schema） |
| [doc/tea-goose-skill.md](doc/tea-goose-skill.md) | 教學用 skill 檔（給 AI 助教讀的） |
| [data/DATA_NOTICE.md](data/DATA_NOTICE.md) | 資料來源聲明 |

## Related

| 專案 | 說明 |
|------|------|
| `../tfc-audit/` | TFC 4,125 篇查核報告的 BERTopic 審計（診斷書） |
| `../icons/` | 吵架鵝 logo |

## License

MIT — 歡迎任何人使用，包括 TFC。
