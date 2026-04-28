<p align="center">
  <img src="doc/logo.webp" alt="Anseropolis Logo" width="200">
</p>

# Anseropolis 🪿

> 台灣茶鵝實驗改良場 — Taiwan Tea Goose Experiment & Improvement Station

語言指紋偵測 × 可疑度評分 = 識別語言操控的工具。

---

## 快速開始

```bash
git clone https://github.com/FakeRocket543/anseropolis.git
cd anseropolis
python3 setup.py
```

安裝完成後，在目錄裡打開 AI Agent（OpenCode / Kiro CLI / Claude Code），貼一段你想分析的內容，agent 會自動引導完成分析。

---

## 為什麼做這個？

現有事實查核機制存在結構性限制：人力有限、選題覆蓋不均、對灰色地帶（如認知作戰、模糊承諾）的處理能力不足。

**Anseropolis 提供一套開源的語言分析工具，讓任何人都能獨立檢視文本的語言模式。**

---

## 架構

```
輸入文字
  ↓
CKIP 斷詞 + 實體提取（人/機構/地/時/事/數字）
  ↓
可疑詞典比對（suspect_lexicon + tao_lexicon）
  ↓
語言指紋分析（詞頻分布 vs 已知來源指紋）
  ↓
Wikidata KG 查詢（驗證人物/機構身份）
  ↓
可疑度評分 + 敘事框架歸類
  ↓
產出：分析報告 + 圖卡
```

## 與 Collatro 的差異

| | Collatro | Anseropolis |
|---|---|---|
| 目標 | 查核事實聲明 | 偵測語言操控模式 |
| 適合 | 謠言、假新聞、數字錯誤 | 認知作戰、帶風向、統戰文本 |
| 方法 | 拆解 → 搜尋 → 比對 | 語言指紋 + 可疑詞典 + 來源比對 |
| 輸出 | 對/錯/不足 | 可疑度分數 + 敘事框架 |
| 判斷 | 有明確對錯 | 沒有對錯，只有「像誰」 |

## 特色

- **語言指紋** — 不靠 LLM 判斷，靠詞彙分布模式識別來源
- **TAO 敘事庫** — 國台辦常用敘事框架的詞典比對
- **可疑度評分** — 語言指紋加權 40 分 > LLM 反駁率 15 分（Nature Comms 2025 實證支撐）
- **Wikidata KG** — 結構化事實驗證人物身份
- **不下結論** — 可疑度高 ≠ 假的，只代表語言模式異常

## 學術基礎

- Ma et al. (2025) *Linguistic features of AI mis/disinformation and the detection limits of LLMs*, Nature Communications
- Wang et al. (2026) *Prompt-Induced Linguistic Fingerprints for LLM-Generated Fake News Detection*, WWW 2026
- Sousa-Silva (2022) *Fighting the Fake: A Forensic Linguistic Analysis*, Int J Semiot Law

## 系統需求

- macOS（Apple Silicon）或 Linux
- Python 3.10+
- AI Agent（OpenCode / Kiro CLI / Claude Code）

## 授權

MIT
