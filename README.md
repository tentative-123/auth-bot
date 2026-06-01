# Auth Bot 專案架構總覽

此專案是一個以 Discord Bot 為入口的「認購權證篩選圖卡工具」。使用者在 Discord 輸入 `a` 加上股票代號後，Bot 會查詢該標的可用的認購權證，依目前篩選與評分邏輯排序，最後輸出一張一頁式 PNG 圖卡。

> 已移除原本的資產配置 / 資金比例分配建議功能；目前保留並專注於權證篩選功能。

---

## 1) 專案檔案結構

```text
auth-bot/
├── main.py                         # Bot 入口、Discord 訊息觸發與回覆流程
├── services/
│   ├── warrant_screener.py          # 權證資料抓取、篩選、即時補值與評分
│   └── warrant_card_renderer.py     # 權證結果 PNG 圖卡產生器
├── requirements.txt                 # Python 套件依賴
├── nixpacks.toml                    # 部署環境設定
└── README.md                        # 本文件
```

---

## 2) 使用方式

在 Discord 頻道輸入：

```text
a2330
```

格式為：

```text
a + 股票代號（4 到 6 碼）
```

例如：

```text
a2408
a6706
a2330
```

Bot 會先回覆查詢中，完成後送出「最佳權證一頁式圖卡」。若圖片渲染失敗，會改用 Discord 文字卡片作為備援輸出。

---

## 3) 權證篩選流程

### 3.1 訊息觸發

`main.py` 監聽所有非 Bot 訊息，當內容符合 `a(\d{4,6})` 時觸發權證查詢流程。

### 3.2 權證資料來源

`services/warrant_screener.py` 會優先嘗試 TWSE 權證資料來源；若無資料，會 fallback 到 Capital 來源。

### 3.3 共同篩選條件

目前主要硬條件包含：

- 只保留認購權證。
- 到期天數介於 90 到 180 天。
- 價內外範圍介於 -15% 到 +10%。
- 最多取前 60 檔候選權證補即時資料與計分。
- 最終依分數排序輸出前 10 檔。

### 3.4 盤中模式

台灣時間平日 `09:00` 到 `13:35` 視為盤中模式。盤中模式會：

- 以昨收作為評分/計算基準，降低盤中跳動造成的評分不穩。
- 顯示昨收與今日現價；若今日沒有成交價，會用買一/賣一中間價推估。
- 篩掉只有單邊掛單的權證，避免流動性不足的標的進入結果。
- 圖卡上顯示「盤中模式」提示。

---

## 4) 圖卡輸出內容

`services/warrant_card_renderer.py` 會產生 PNG 圖卡，包含：

- 標的股票代號與現價。
- 權證代號與名稱。
- 成交量。
- 昨收 / 今日現價。
- 剩餘天數。
- 價外 / 價內比例。
- 差槓比。
- 槓桿。
- 底部條件提示。
- 右上角出品提示文字。

---

## 5) 外部整合

- **Discord API**：接收訊息、發送查詢狀態、圖片與備援文字卡。
- **TWSE / MIS API**：查詢權證清單、標的價格、權證即時成交與五檔資訊。
- **Capital 權證資料來源**：TWSE 查無資料時的 fallback。
- **Pillow**：產生一頁式 PNG 圖卡。

---

## 6) 環境變數

執行前需設定任一 Discord Token 變數：

- `DISCORD_TOKEN`
- `DISCORD_BOT_TOKEN`
- `discord_token`

目前不需要 `OPENAI_API_KEY`，也不再提供 `$health` 資產配置分析功能。

---

## 7) 安裝與執行

```bash
pip install -r requirements.txt
python main.py
```

---

## 8) 注意事項

- Bot 需要在 Discord Developer Portal 開啟 Message Content Intent，否則可能收不到一般文字訊息內容。
- 權證即時資料依外部資料源回傳為準；若來源暫時無資料，Bot 會回覆查無可用權證或使用備援文字卡。
- 圖卡首次產生時可能會下載中文字型檔，以確保中文能正常顯示。
