# TG AI Monitor

這個專案是一個 Telegram 監聽程式骨架，使用使用者帳號 session 來接收帳號可看到的群組與頻道訊息，並把資料存下來，供後續分析使用。

目前先聚焦在兩個目標：

1. 判斷訊息是否和遊戲清單更新有關。
2. 統計指定使用者 ID 的回覆次數與回覆品質。

## 目前採用方式

這個骨架目前使用 `Telethon` 的使用者帳號模式，不是 bot token。

原因：

- 你的目標是監聽帳號所在的群組與頻道內容。
- 這類需求通常用使用者 session 會比較直接，也比較符合後續擴充方向。

## 專案結構

```text
src/tg_monitor/
  analyzers.py      訊息分類與回覆品質評分
  config.py         環境變數設定
  listener.py       Telegram 監聽邏輯
  main.py           主程式入口
  report.py         指定使用者回覆統計輸出
  storage.py        SQLite 儲存
```

## 這一版骨架已包含

- 監聽 Telegram 群組、超級群組、頻道訊息
- 把 chat、user、message 存進 SQLite
- 初步判斷訊息是否和遊戲清單更新有關
- 用簡單規則先做回覆品質評分
- 輸出指定使用者的回覆統計

## 安裝

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

也可以直接使用 Windows CMD 腳本：

```cmd
install_deps.cmd
```

## 設定

請先把 `.env.example` 複製成 `.env`，再填入實際值。

主要欄位如下：

- `TG_API_ID`
- `TG_API_HASH`
- `TG_SESSION_NAME`
- `TRACKED_USER_IDS`
- `CHAT_BLOCKLIST_IDS`
- `AUTO_MARK_READ`
- `AUTO_MARK_READ_DELAY_MIN_SECONDS`
- `AUTO_MARK_READ_DELAY_MAX_SECONDS`
- `SQLITE_PATH`

範例：

```env
TG_API_ID=123456
TG_API_HASH=your_api_hash
TG_SESSION_NAME=tg-ai-monitor
TRACKED_USER_IDS=123456789,987654321
CHAT_BLOCKLIST_IDS=-1001234567890,-5347871611
AUTO_MARK_READ=false
AUTO_MARK_READ_DELAY_MIN_SECONDS=0
AUTO_MARK_READ_DELAY_MAX_SECONDS=60
SQLITE_PATH=data/tg_monitor.db
```

`TRACKED_USER_IDS` 是記錄白名單，留空代表所有使用者訊息都記錄。填入後仍會監聽所有群組與頻道，但只有指定 user id 的訊息會寫進 SQLite。

`CHAT_BLOCKLIST_IDS` 是群組 / 頻道黑名單，留空代表不排除任何來源。填入後指定 chat id 內的訊息不會寫進 SQLite。

兩個條件可以同時使用：先排除 chat 黑名單，再檢查 sender user id 是否需要記錄。

`AUTO_MARK_READ` 是自動已讀 ACK 開關，預設 `false`。開啟後，只有通過 `CHAT_BLOCKLIST_IDS` 與 `TRACKED_USER_IDS` 條件、且已成功寫入 SQLite 的新訊息，才會排程標記已讀。

`AUTO_MARK_READ_DELAY_MIN_SECONDS` 和 `AUTO_MARK_READ_DELAY_MAX_SECONDS` 控制 ACK 前的隨機等待秒數。預設是 `0` 到 `60` 秒，因此會在收到並記錄訊息後，隨機等待最多 60 秒再標記已讀。

這個功能不會自動回覆、轉發或發送訊息，只會呼叫 Telegram 的 read acknowledge。編輯事件不會觸發 ACK。

## 執行監聽

```powershell
python -m src.tg_monitor.main
```

或使用 Windows CMD 腳本：

```cmd
run_listener.cmd
```

第一次執行時，Telethon 會要求在終端登入驗證，並建立本機 session 檔案。

## 查看指定使用者統計

```powershell
python -m src.tg_monitor.report
```

或使用 Windows CMD 腳本：

```cmd
run_report.cmd
```

## 目前儲存的資料

SQLite 會把資料拆成三類，不把兩個目標混在同一張原始訊息表裡。

`raw_messages` 只存 Telegram 原始訊息：

- chat id
- sender user id
- message id
- 原始訊息文字
- reply 對應的 message id
- UTC 時間

`game_list_analysis` 只存遊戲清單整理用的判斷：

- chat id
- message id
- 是否疑似遊戲清單相關
- 判斷原因
- 分析時間

`user_reply_analysis` 只存 USER 考核用的判斷：

- chat id
- message id
- user id
- 是否為 reply
- 回應內容類型
- 回應內容類型原因
- 回覆品質分數
- 回覆品質說明
- 分析時間

另外還有輔助表：

- `chats`
- `users`

## 回覆品質評分

目前只是第一版規則式評分，目的是先把資料流接起來，方便後續調整。

大方向是：

- 太短、太空泛的回覆會扣分
- 有明確處理資訊、說明、結構的回覆會加分
- 分數區間限制在 `0` 到 `100`

## 統計輸出範例

```text
user_id=123456789 replies=18 avg_quality=74.2 high_quality=9 game_list_related=4
```

## 後續可再擴充

- 改成更準確的遊戲清單更新判斷規則
- 串接 OpenAI 做訊息分析
- 加入每日摘要或排程報表
- 加入群組 / 頻道白名單與黑名單
- 匯出 CSV 或提供 API
- 做簡單 dashboard

## 訊息編輯追蹤

`raw_messages` 目前保留同一筆 Telegram 訊息的最新內容，不保存每次編輯的歷史版本。

同一個 `chat_id + message_id` 再次被看到時：

- `text` 會更新成目前最新內容
- `edited_at` 會記錄 Telegram 提供的編輯時間
- `edit_count` 會在文字內容真的改變時加 1
- `last_seen_at` 會記錄程式最後一次看到這筆訊息的時間

`.xlsx` 匯出也會帶出 `edited_at`、`edit_count`、`last_seen_at`，方便人工檢查訊息是否曾被編輯。
