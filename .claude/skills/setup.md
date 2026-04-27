# Anseropolis 環境設定 Skill

## 觸發條件

當學生第一次使用 Anseropolis，或遇到 ImportError / 環境問題時，執行以下引導。

## 自動設定流程

請依序執行以下步驟，每步確認成功後再繼續：

### 1. 確認 Python 版本
```bash
python3 --version
```
需要 3.11+。

### 2. 安裝依賴
```bash
pip install mlx-lm playwright numpy jieba pyyaml
```

### 3. 安裝瀏覽器引擎
```bash
playwright install chromium
```

### 4. 下載 LLM 模型（首次約 4.5GB）
```bash
python3 -c "from mlx_lm import load; load('mlx-community/Ministral-8B-Instruct-2412-4bit')"
```

### 5. （選配）安裝 CKIP 斷詞
```bash
pip install ckip-transformers
```
如果不裝，會自動 fallback 到 jieba（較不準但能用）。

### 6. 驗證
```bash
cd /path/to/anseropolis
python3 -m src.run "網傳台積電整廠搬遷美國"
```
如果看到 `🪿 完成！` 就成功了。加 `--theme sky` 可以產圖卡。

## 常見問題

- **mlx-lm 安裝失敗**：需要 Apple Silicon。Intel Mac 改連老師 server
- **numpy 版本衝突**：`pip install --upgrade numpy`
- **CKIP 載入慢**：第一次會下載 BERT 模型（~400MB×2），之後快取
- **記憶體不足**：用 3B 模型 `ANSEROPOLIS_MLX_MODEL=mlx-community/Ministral-3B-Instruct-2512-4bit`

## 如果學生沒有 Apple Silicon

```bash
export ANSEROPOLIS_LLM_URL=http://老師IP:8080/v1/chat/completions
pip install playwright numpy jieba pyyaml
playwright install chromium
```
不需要 mlx-lm，LLM 步驟由老師的 server 處理。ingest/match/score 仍在本地跑。
