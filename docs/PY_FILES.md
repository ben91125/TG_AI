# Python 檔案功能簡述

這份文件用來快速理解目前專案中每個 `.py` 檔案的大致責任。後續如果新增模組，建議同步更新這份文件，避免只靠檔名猜功能。

## 專案入口與設定

### `src/__init__.py`

頂層 package marker，讓 `python -m src.tg_monitor...` 這類模組執行方式可以正常運作。

目前沒有業務邏輯。

### `src/tg_monitor/__init__.py`

`tg_monitor` package marker。

目前沒有業務邏輯。

### `src/tg_monitor/main.py`

Telegram 監聽主程式入口。

主要責任：

- 載入 `.env` 設定。
- 初始化 logging。
- 建立 `SQLiteStore`。
- 建立 Telegram client。
- 註冊 listener event handler。
- 啟動 Telegram 連線並持續監聽。
- 程式結束時輸出 tracked user summary。

常用執行方式：

```cmd
run_listener.cmd
```

### `src/tg_monitor/config.py`

集中處理環境變數設定。

主要責任：

- 從 `.env` 載入 `TG_API_ID`、`TG_API_HASH`、`TG_SESSION_NAME`、`TRACKED_USER_IDS`、`SQLITE_PATH`、`LOG_LEVEL`。
- 將 `TRACKED_USER_IDS` 從逗號字串轉成 `set[int]`，供 listener 過濾指定使用者。
- 將 `CHAT_BLOCKLIST_IDS` 從逗號字串轉成 `set[int]`，供 listener 排除指定群組 / 頻道。
- 載入 `AUTO_MARK_READ` 與隨機 ACK 延遲秒數，供 listener 決定是否自動標記已讀。
- 建立 SQLite 檔案所在資料夾。
- 回傳 `Settings` dataclass。

注意：

- `.env` 不會進 git。
- `TRACKED_USER_IDS` 可以先留空，不影響監聽所有群組與頻道。

## Telegram 監聽

### `src/tg_monitor/listener.py`

Telegram event handler 所在檔案。

主要責任：

- 建立 `TelegramClient`。
- 註冊 `events.NewMessage()` handler。
- 過濾出群組、超級群組、頻道訊息。
- 取得 chat、sender、message、reply 資訊。
- 先寫入 `raw_messages`。
- 再分別寫入 `game_list_analysis` 和 `user_reply_analysis`。

目前資料流：

```text
Telegram message
-> RawMessage
-> GameListAnalysis
-> UserReplyAnalysis
-> SQLite
```

注意：

- 私訊目前不寫入，因為目標是監聽帳號所在的群組與頻道。
- 若 `.env` 設定 `CHAT_BLOCKLIST_IDS`，指定 chat id 內的訊息會被略過。
- 若 `.env` 設定 `TRACKED_USER_IDS`，仍會監聽所有群組與頻道，但只有指定 user id 的訊息會寫入。
- 若 `.env` 設定 `AUTO_MARK_READ=true`，通過過濾且已寫入 DB 的新訊息會在隨機延遲後標記已讀。
- 純空文字訊息目前會略過。

## SQLite 資料層

### `src/tg_monitor/storage.py`

SQLite schema 與資料寫入邏輯。

主要 dataclass：

- `RawMessage`：Telegram 原始訊息。
- `GameListAnalysis`：遊戲清單整理用分析結果。
- `UserReplyAnalysis`：USER 考核用初步分析結果。

主要資料表：

- `chats`：群組 / 頻道資訊。
- `users`：使用者資訊。
- `raw_messages`：原始訊息，不放任務判斷或考核分數。
- `game_list_analysis`：遊戲清單整理判斷。
- `user_reply_analysis`：USER 回覆類型與品質初步判斷。

其他責任：

- 若舊版 `messages` 表存在，啟動時會將舊資料遷移到新表。
- `tracked_user_summary()` 目前只查 `user_reply_analysis`，不再混入 game list 欄位。

設計重點：

- `raw_messages` 必須保持乾淨。
- 遊戲清單整理和 USER 考核共用原始資料來源，但分析結果分開存。

## 遊戲清單整理

### `src/tg_monitor/game_list/__init__.py`

`game_list` package marker。

目前沒有業務邏輯。

### `src/tg_monitor/game_list/classifier.py`

遊戲清單整理的初步規則分類器。

主要責任：

- 根據關鍵字判斷訊息是否可能和遊戲清單異動有關。
- 回傳 `GameListResult`，包含 `is_related` 和 `reason`。

目前判斷仍是規則式，適合當作第一層候選訊息篩選。後續可以再加入更精準的 rule 或 AI 判斷，但應維持在 game list 模組內，不和 USER 考核混在一起。

## USER 考核

### `src/tg_monitor/user_review/__init__.py`

`user_review` package marker。

目前沒有業務邏輯。

### `src/tg_monitor/user_review/classifier.py`

USER 回覆分析的初步規則分類器。

主要責任：

- 將訊息分成初步 `response_type`，例如 `low_signal`、`action_update`、`explanation`、`question`。
- 依據訊息長度、是否 reply、是否有行動字眼、是否過短等規則給 `quality_score`。
- 回傳 `UserReplyResult`。

目前狀態：

- USER 考核自動化先 pending。
- 現有分數只當人工觀察參考，不作為最終考核結論。

## 匯出與查詢

### `src/tg_monitor/report.py`

命令列版 tracked user summary。

主要責任：

- 讀取 `.env` 裡的 `TRACKED_USER_IDS`。
- 從 `user_reply_analysis` 統計指定 user 的 reply 數、平均品質分數、高品質與低品質數。

常用執行方式：

```cmd
run_report.cmd
```

目前如果 `TRACKED_USER_IDS` 留空，會顯示沒有 tracked-user reply data。

### `src/tg_monitor/export_xlsx.py`

將 SQLite 目前內容匯出成 `.xlsx` 快照。

主要責任：

- 讀取 SQLite。
- 建立 Excel workbook。
- 將不同資料表 / join 結果放進不同 sheet。
- 設定基本欄寬、凍結表頭、filter、換行。
- 輸出到 `outputs/reports/`。
- 支援 `--start` / `--end` 指定匯出時間範圍，未指定時完整匯出。
- 檔名會用 `_all` 或 `_range_開始_to_結束` 標示是否為全量匯出。

目前 sheet：

- `ExportInfo`
- `RawMessages`
- `GameListAnalysis`
- `UserReview`
- `Chats`
- `Users`

常用執行方式：

```cmd
run_export_xlsx.cmd
```

定位：

- 目前這是 debug snapshot，方便人工看資料。
- 後續正式報表應拆成 `GameList` 專用 xlsx 與 `UserReview` 專用 xlsx。

## 相容與包裝

### `src/tg_monitor/analyzers.py`

目前是相容包裝檔。

原本遊戲清單與 USER 回覆分析都寫在這個檔案裡，後來已拆到：

- `src/tg_monitor/game_list/classifier.py`
- `src/tg_monitor/user_review/classifier.py`

此檔案目前只重新 export 兩邊的 public function / result class，避免未來若有舊 import 路徑時完全斷掉。

## 訊息編輯追蹤補充

`src/tg_monitor/listener.py` 同時處理 `events.NewMessage()` 與 `events.MessageEdited()`。

編輯後的 Telegram 訊息會走同一條 `_handle_message_event()` 流程，並用 `chat_id + message_id` 更新同一筆 `raw_messages`。

`src/tg_monitor/storage.py` 目前採用「保留最新版本內容」策略：

- `text` 保存最新內容
- `edited_at` 保存 Telegram 編輯時間
- `edit_count` 保存文字內容變更次數
- `last_seen_at` 保存程式最後一次看到該訊息的時間

`src/tg_monitor/export_xlsx.py` 匯出的 `RawMessages`、`GameListAnalysis`、`UserReview` 也會包含 `edited_at`、`edit_count`、`last_seen_at`，避免 SQLite 已有欄位但 Excel 看不到。
