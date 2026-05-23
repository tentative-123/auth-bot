# Auth Bot 專案架構總覽

此專案是一個以 Discord Bot 為入口的「資產配置風險分析工具」，使用者透過指令輸入持倉資訊後，系統會完成：
1. 資產配置解析與標準化
2. 市場波動資料抓取與風險評分
3. 視覺化圖表產出
4. AI 文字評語回覆

---

## 1) 專案檔案結構

```text
auth-bot/
├── main.py            # Bot 入口、Discord 指令與互動流程
├── analysis.py        # 市場資料、風險計算、圖表生成、AI 評語工具函式
├── requirements.txt   # Python 套件依賴
└── README.md          # 本文件
```

---

## 2) 系統流程（高層）

### Stage 1：輸入解析與確認（`main.py`）
- 使用者透過 `$health` 指令輸入資產配置（可混合比例/金額/自然語言）。
- Bot 透過 OpenAI 將輸入標準化成 JSON（`assets` + `total`）。
- Bot 回傳初步計算結果，並附上「確認/修改」按鈕供使用者互動。

### Stage 2：按鈕互動確認（`ConfirmView`）
- 僅允許原始發送者操作按鈕（避免他人誤觸）。
- 按下「✅ 確認正確」後進入分析程序。
- 按下「❌ 修改」則結束本次流程。

### Stage 3：分析、圖表與 AI 評語
- 呼叫 `analysis.fetch_market_data()`：
  - 過濾現金類資產
  - 使用 Yahoo Finance（`yfinance`）抓取一年收盤價
  - 計算年化波動率並換算風險分
- 呼叫 `analysis.generate_charts()`：
  - 輸出資產配置圓餅圖 + 風險分橫條圖
- 使用 OpenAI 生成兩段式評語：
  - 風險等級與預期波動
  - 可執行的優化建議
- 最後將圖與文字一起回覆到 Discord。

---

## 3) 模組與責任劃分

## `main.py`
- 初始化 Discord Bot（包含 intents 與 command prefix）。
- 初始化 `AsyncOpenAI` 客戶端（讀取 `OPENAI_API_KEY`）。
- 定義互動元件 `ConfirmView`（按鈕行為/權限控制）。
- 提供 `$health` 指令作為主要入口。
- 負責 Bot 啟動（讀取 `DISCORD_TOKEN`）。

## `analysis.py`
- 字型處理：首次執行可自動下載中文字型，避免圖表中文顯示異常。
- 資料處理：
  - `fetch_market_data(assets)` 計算各資產波動率與整體風險分。
- 圖表處理：
  - `generate_charts(assets, total_score)` 生成 PNG 圖片緩衝區。
- AI 工具函式：
  - `get_ai_critique(...)` 可產生進一步評論（目前主流程在 `main.py` 內直接呼叫 OpenAI）。

---

## 4) 外部整合

- **Discord API**：接收指令、發送訊息、按鈕互動。
- **OpenAI API**：
  - Stage 1 做輸入結構化
  - Stage 3 做投資配置文字評語
- **Yahoo Finance (`yfinance`)**：抓取市場歷史價格。
- **Matplotlib**：生成視覺化圖表。

---

## 5) 環境變數

執行前需設定：

- `DISCORD_TOKEN`：Discord Bot Token
- `OPENAI_API_KEY`：OpenAI API Key

若未設定 `OPENAI_API_KEY`，Bot 會提示錯誤並無法執行 `$health` 分析流程。

---

## 6) 目前設計特色與注意事項

### 特色
- 採用按鈕確認機制，避免直接用錯誤解析結果進行分析。
- 對「現金」與「抓不到行情」做 fallback（預設波動率），避免流程中斷。
- 圖表整合文字評語，輸出更完整。

### 注意事項
- 目前使用模型名稱為 `gpt-4-turbo-preview`，若 API 版本更新可統一調整。
- `analysis.py` 內仍存在一個未 `await` 的 `get_ai_critique` 寫法（函式雖標示 `async`，但內部呼叫是同步風格），主流程目前未使用該函式，不影響現行操作，但建議後續整理。

---

## 7) 安裝與執行

```bash
pip install -r requirements.txt
python main.py
```

在 Discord 中輸入範例：

```text
$health 50% VOO, 30% TSMC, 20% 現金
```

