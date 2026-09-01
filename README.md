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
b2330
```

格式為：

```text
a + 股票代號：認購權證篩選
b + 股票代號：認售權證篩選
```

4/5 碼數字或 `00631L` / `00632R` 這類槓反 ETF 代號會執行最佳權證篩選；6 碼數字會查單檔權證參數。認售 `b` 指令也支援 `03206T` 這類 5 碼數字加 1 碼英文字母的單檔權證代號；但 `00631L` / `00632R` 這類槓反 ETF 代號會優先視為標的股號，不會誤判成單檔權證。

例如：

```text
a2408
a2330
b2330
b069191
```

Bot 會先回覆查詢中，完成後送出「最佳權證一頁式圖卡」。若圖片渲染失敗，會改用 Discord 文字卡片作為備援輸出。

---

## 3) 權證篩選流程

### 3.1 訊息觸發

`main.py` 監聽所有非 Bot 訊息：`a` 開頭代表認購，`b` 開頭代表認售；4/5 碼數字或 `00631L` / `00632R` 這類槓反 ETF 代號會執行最佳權證篩選，6 碼數字會改查單檔權證參數並用 Discord 文字卡片輸出。認售 `b` 指令另外支援 `03206T` 這類 5 碼數字加英文字母的單檔權證代號，但 `00631L` / `00632R` 會保留為槓反 ETF 標的篩選。

### 3.2 單檔權證參數查詢

輸入 `a` + 6 碼數字會查詢單檔認購權證參數；輸入 `b` + 6 碼數字或 5 碼數字加英文字母會查詢單檔認售權證參數，例如：

```text
a060556
b069191
b03206T
```

此模式會用 Discord 文字卡片輸出權證代號 / 名稱、標的代號、權證昨收 / 現價、買一 / 賣一、剩餘天數、履約價、行使比例、Capital 有提供時的隱波與在外流通率、槓桿、差槓比與近日成交量；卡片會使用較完整的參數名稱與手機友善的分行摘要，避免欄位擠在同一行造成閱讀困難。

### 3.3 查詢排隊與快取

權證查詢會先進入 Bot 內部佇列，依照使用者呼叫的先後順序逐筆查詢，避免多人同時查詢時一起打外部資料源。

同一個股號在 1 小時內會重用快取結果；可用 `WARRANT_CACHE_TTL_SECONDS` 調整快取秒數，預設 `3600`。

### 3.4 權證資料來源

`services/warrant_screener.py` 會優先嘗試 TWSE 權證資料來源；若無資料，會 fallback 到 Capital 來源。Capital 的舊式回應會優先以台灣舊站使用的 CP950 / Big5 解碼，並支援 UTF-8；候選權證名稱也會再以 MIS 即時資料校正，避免部分個股名稱出現亂碼。

### 3.5 共同篩選條件

目前主要硬條件包含：

- 只保留認購權證。
- 到期天數介於 70 到 180 天。
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

---

## 9) Google Sheet 訂閱權限管理（選用）

此 Bot 也可以選用 Google Sheet 作為訂閱審核後台。使用者填寫表單後，管理員在 Sheet 的「後台核對」欄填入 `OK`，Bot 會在指定 Discord 頻道發送確認按鈕；使用者本人點擊後，Bot 會幫他加入指定身分組，並把該使用者的 Discord ID、訂閱時間與到期日回填到 Google Sheet。

### 9.1 建議 Sheet 欄位

既有欄位可沿用圖片中的欄位，至少需要：

- `您的 Discord (DC) 帳號名稱`
- `後台核對`
- `訂閱時間`
- `到期日`

Bot 啟動後會自動補上以下欄位（如果 Sheet 第一列不存在）：

- `Discord User ID`
- `Bot 通知狀態`
- `Bot 通知訊息 ID`
- `Discord 確認時間`
- `開通錯誤訊息`
- `到期前14天提醒`
- `到期前7天提醒`
- `到期前3天提醒`
- `到期處理狀態`
- `到期移除時間`

### 9.2 名稱與 ID 的處理方式

目前流程允許使用者先只填 Discord 名稱。Bot 會嘗試用該名稱在 Discord 伺服器中找到會員並標記；如果名稱無法精準找到，Bot 仍會用文字顯示該名稱並請本人點擊按鈕。使用者點擊後，Bot 會先比對點擊者 Discord 名稱與表單名稱；通過後才會把 `interaction.user.id` 回填到 `Discord User ID` 欄位，之後同一列就會以 ID 為準避免誤開。

### 9.3 必要 Discord 設定

- Bot 需要 `Manage Roles` 權限。
- Bot 的最高身分組必須高於要發放的訂閱身分組。
- `後台核對` 填 `ok` 會發放 `DISCORD_SUBSCRIBER_ROLE_ID` 對應的「權證」身分組；填 `ok2` 會發放 `DISCORD_SUBSCRIBER_ROLE_ID_2` 對應的「權證2」身分組。
- 若希望 Bot 更容易用名稱找到使用者，請在 Discord Developer Portal 開啟 Server Members Intent，並確認 Bot 使用 members intent。

### 9.4 通知頻道與隱私

Discord 一般頻道訊息無法設定成「只有被標記的人可見」；只有互動回覆可以是 ephemeral（僅點擊者可見）。如果開通提示要更私密，可以設定：

```env
SUBSCRIPTION_NOTIFY_MODE=dm
```

此模式會優先私訊找到的使用者並附上開通按鈕；如果 Bot 找不到該名稱或使用者關閉私訊，才會退回 `DISCORD_NOTIFY_CHANNEL_ID` 指定的頻道發送。建議把 `DISCORD_NOTIFY_CHANNEL_ID` 設成「驗證/開通」用公開或半公開頻道，而不是訂閱會員專屬頻道，因為未訂閱者還看不到會員頻道。

---

### 9.5 權證查詢頻道限制

如果不希望公開頻道也能使用權證查詢，可以設定：

```env
WARRANT_ALLOWED_CHANNEL_IDS=頻道ID1,頻道ID2
```

設定後，`a2330` 這類權證查詢只會在列出的頻道生效；未設定時則維持所有 Bot 可讀頻道都可使用。


### 9.6 續約與到期提醒

Bot 會掃描已開通且有 `Discord User ID` / `到期日` 的列，並在到期前自動提醒：

- 到期前 14 天
- 到期前 7 天
- 到期前 3 天

提醒會優先私訊使用者；若私訊失敗，會退回 `DISCORD_NOTIFY_CHANNEL_ID` 指定頻道標記提醒。每個提醒階段送出後，Bot 會把送出時間寫入對應欄位，避免重複提醒。

續約時，使用者填寫同一份表單，管理員一樣在新列的 `後台核對` 填 `OK`。使用者點擊新列的確認按鈕後，Bot 會尋找該 Discord ID（或同名資料）既有的最新 `到期日`：

- 如果原到期日仍在今天或未來：新到期日 = 原到期日 + 3 個月。
- 如果已經過期或找不到既有到期日：新到期日 = 本次確認時間 + 3 個月。

每一筆表單列的確認按鈕只會生效一次。首次開通成功後，Bot 會移除該訊息的按鈕；即使使用者在舊畫面重複觸發，Bot 也會依據 Sheet 的 `已開通` / `訂閱時間` 狀態阻止重複延長。


### 9.7 手動延長指定用戶期限

可以直接在 Google Sheet 手動修改該用戶最新一筆 `到期日` 欄位，格式建議使用 `YYYY-MM-DD`，例如 `2026-09-15`。Bot 的到期提醒與續約延展都會讀取 Sheet 目前的 `到期日`：

- 手動改晚一點：系統會以新的日期作為提醒與續約基準。
- 用戶未過期前續約：新到期日會從目前最新的 `到期日` 再加 3 個月。
- 修改後若不想讓同一階段提醒再次發送，請保留對應的 `到期前14天提醒` / `到期前7天提醒` / `到期前3天提醒` 欄位；若想重新提醒，才清空對應欄位。


### 9.8 到期後自動移除身分組

Bot 會在會員到期後保留 3 天緩衝期，超過緩衝期後才自動移除訂閱身分組。移除完成後會回填：

- `到期處理狀態 = 已移除`
- `到期移除時間 = 實際移除時間`

如果使用者已經成功續約，Bot 只會以該 Discord ID 最新的一筆有效 `到期日` 判斷，不會因舊訂閱列過期而誤移除身分組。

若要讓特定用戶不被自動移除，可以在 `到期處理狀態` 填入白名單狀態，預設支援：

- `保留`
- `白名單`
- `不移除`
- `手動延長`

白名單值可用 `SHEET_EXPIRY_WHITELIST_VALUES` 自訂；到期後幾天移除可用 `SUBSCRIPTION_EXPIRY_GRACE_DAYS` 調整，預設 `3`。

### 9.9 必要 Google 設定

1. 建立 Google Cloud Project。
2. 啟用 Google Sheets API。
3. 建立 Service Account。
4. 建立 Service Account JSON key。
5. 將 Google Sheet 分享給 Service Account email，權限設為編輯者。

### 9.10 環境變數

啟用此功能需要額外設定：

```env
SUBSCRIPTION_SYNC_ENABLED=true
GOOGLE_SHEET_ID=你的 spreadsheet id
GOOGLE_WORKSHEET_NAME=Form_Responses
GOOGLE_SERVICE_ACCOUNT_JSON={...整份 service account json...}
DISCORD_GUILD_ID=你的 Discord server id
DISCORD_NOTIFY_CHANNEL_ID=要發送確認按鈕的頻道 id
DISCORD_SUBSCRIBER_ROLE_ID=後台核對為 ok 時要開通的「權證」身分組 id
DISCORD_SUBSCRIBER_ROLE_ID_2=後台核對為 ok2 時要開通的「權證2」身分組 id
SHEET_CHECK_INTERVAL_SECONDS=60
SUBSCRIPTION_NOTIFY_MODE=channel
SUBSCRIPTION_EXPIRY_GRACE_DAYS=3
```

如果不想把 JSON 放進環境變數，也可以改用檔案路徑：

```env
GOOGLE_APPLICATION_CREDENTIALS=/app/google-service-account.json
```

> `GOOGLE_WORKSHEET_NAME` 必須填 Google Sheet 底部分頁的「工作表分頁名稱」，不是表單回應表格左上角的表格名稱。若 Railway log 出現 `WorksheetNotFound: Form_Responses`，請到試算表底部分頁確認實際名稱，常見可能是 `表單回應 1`、`Form Responses 1`，或你自行改名後的名稱；也可以把 `GOOGLE_WORKSHEET_NAME` 留空，Bot 會使用第一個工作表分頁。

### 9.11 可調整欄位名稱

如果你的 Sheet 欄位名稱不同，可以用環境變數覆蓋：

```env
SHEET_COL_DISCORD_NAME=您的 Discord (DC) 帳號名稱
SHEET_COL_REVIEW=後台核對
SHEET_COL_SUBSCRIBED_AT=訂閱時間
SHEET_COL_EXPIRES_AT=到期日
SHEET_COL_DISCORD_ID=Discord User ID
SHEET_COL_REMINDER_14=到期前14天提醒
SHEET_COL_REMINDER_7=到期前7天提醒
SHEET_COL_REMINDER_3=到期前3天提醒
SHEET_COL_EXPIRY_STATUS=到期處理狀態
SHEET_COL_EXPIRY_REMOVED_AT=到期移除時間
SHEET_EXPIRY_WHITELIST_VALUES=保留,白名單,不移除,手動延長
SHEET_APPROVED_VALUES=OK,ok,ok2,通過,已核對
```
