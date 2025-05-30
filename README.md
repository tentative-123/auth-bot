# auth-bot
Discord管理用的機器人

# Auth-Bot 訂閱授權機器人

一個簡易的 Discord 授權管理機器人，讓你可以手動授權用戶並指定有效期限，並自動給予對應身份組。

---

## 🔧 功能
- `!auth @使用者 30`：授權使用者 30 天訂閱權限，並給予指定身分組
- `!checkauth @使用者`：查詢授權期限與狀態
- 授權紀錄儲存於 `subs.json`，重啟後不遺失

---

## 📦 安裝相依套件
```bash
pip install -r requirements.txt
```

---

## 🚀 執行方式
1. 建立 `.env` 或設定環境變數：
```
AUTH_BOT_TOKEN=你的 Discord Bot Token
```

2. 執行機器人：
```bash
python main.py
```

---

## 🧩 Discord 設定建議
- 機器人需擁有 `Manage Roles` 權限
- 在 Discord 中建立一個身分組名稱為 `premium_user`
- 機器人加入你的伺服器

---

## 📁 檔案說明
| 檔案         | 說明                     |
|--------------|--------------------------|
| `main.py`    | 主程式，管理授權指令     |
| `subs.json`  | 使用者授權紀錄資料檔     |
| `requirements.txt` | 所需 Python 套件清單 |

---

## 🗂 授權紀錄格式範例
```json
{
  "123456789012345678": {
    "start": "2025-05-30",
    "end": "2025-06-29"
  }
}
```

---

## 📬 建議用法
可搭配 Google 表單申請、Webhook 通知你審核後再用 `!auth` 指令發授權。

---

如需更多擴充功能（自動移除、到期提醒、LINE 推播）歡迎擴充使用！
