# 版本脈絡紀錄

## 2026-07-13

### Telegram 監聽骨架

建立 Telegram 使用者帳號模式的監聽程式，目標是接收帳號可看到的群組與頻道訊息。

主要內容：

- 使用 `Telethon` 建立 Telegram client。
- 透過 `.env` 管理 `TG_API_ID`、`TG_API_HASH`、session name、SQLite path。
- 監聽群組、超級群組、頻道訊息。
- 使用 SQLite 作為本機資料庫。
- 新增 Windows CMD 腳本，方便用固定方式安裝依賴、啟動監聽、查詢報表。

### 資料表拆分

原本 `messages` 表同時包含原始訊息、遊戲清單判斷、USER 回覆品質分數。後續發現這會把兩個目標混在一起，因此改成三組資料：

- `raw_messages`：只保存 Telegram 原始訊息。
- `game_list_analysis`：只保存遊戲清單整理用的判斷結果。
- `user_reply_analysis`：只保存 USER 考核用的初步判斷結果。

拆分原因：

- 遊戲清單整理是任務導向。
- USER 考核是人員評估導向。
- 兩者共用原始訊息資料來源，但分析結果不應混在同一張原始訊息表。

目前策略：

- `raw_messages` 保持乾淨，不放評分或任務判斷。
- 舊 `messages` 表先保留，不刪除。
- 啟動 store 時會把舊 `messages` 內容遷移到新表。

### Excel 快照匯出

新增 `.xlsx` 快照匯出功能，先用於人工檢視資料，不作為最終正式報表。

輸出位置：

```text
outputs/reports/tg_monitor_snapshot_YYYYMMDD_HHMMSS.xlsx
```

目前 sheet：

- `RawMessages`：原始訊息。
- `GameListAnalysis`：遊戲清單判斷。
- `UserReview`：USER 回覆分析初步資料。
- `Chats`：群組 / 頻道統計。
- `Users`：使用者統計。

後續方向：

- `GameList` 應獨立成專用 `.xlsx`，服務遊戲清單整理。
- `UserReview` 應獨立成專用 `.xlsx`，服務 USER 考核。
- 目前 USER 考核自動評分先 pending，只保留欄位和初步規則供人工觀察。

