# Telegram 歷史訊息匯出器

這是獨立工具，不會讀寫 `src/tg_monitor` 或現有機器人的 `.env`、session、data 與 outputs。

## 帳號設定

複製 `accounts/example.env`，例如建立 `accounts/account_a.env`：

```dotenv
TG_API_ID=123456
TG_API_HASH=your_api_hash
TG_PHONE=+886900000000
```

可建立多份帳號設定，例如 `account_a.env`、`account_b.env`。每個 account 名稱各自使用 `sessions/<account>.session`，可安全切換多個帳號。帳號 env、session 與匯出內容均已由此目錄的 `.gitignore` 排除。

第一次執行會由 Telegram 要求登入碼；若帳號有兩步驟驗證，也會在終端機要求密碼。請勿把登入碼、密碼或 session 檔交給他人。

## 執行

互動模式：

```powershell
.\run_export.cmd
```

未提供 `--account` 時，程式會掃描 `accounts/*.env`（不包含 `example.env`）並顯示編號選單：

```text
偵測到以下帳號設定：
1. account_a
2. account_b
請選擇帳號 [1-2]:
```

直接指定帳號並匯出（會繼續詢問完整歷史或日期範圍）：

```powershell
.\run_export.cmd --account account_a --chat-id 6450183261
```

未指定日期時仍會詢問「完整歷史／指定日期範圍」。若要完全非互動地指定日期：

```powershell
.\run_export.cmd --account account_a --chat-id 6450183261 --from-date 2026-07-20 --to-date 2026-08-07
```

月份結束後，可重新向 Telegram 取得完整月份並更新正式月檔：

```powershell
.\run_export.cmd --account account_a --chat-id 6450183261 --month 2026-07
```

互動模式中這是第 3 個選項。只能指定已結束月份；本月與未來月份會被拒絕。程式先寫入暫存檔，再與既有正式月檔依 `msg_id + event_type` 合併：Telegram 的新快照會更新同一訊息，舊月檔獨有的紀錄仍會保留。完成解析驗證後才原子替換正式月檔，中斷時不會破壞舊檔。

只寫媒體 metadata、不下載檔案：

```powershell
.\run_export.cmd --account account_a --chat-id 6450183261 --no-media
```

Media 預設同時下載 3 個，每次最多等待 120 秒，失敗後重試 2 次。可自行調整：

```powershell
.\run_export.cmd --account account_a --chat-id 6450183261 --media-workers 2 --media-timeout 90 --media-retries 3
```

執行期間每批或至少約每 5 秒顯示目前日期、掃描／新增／略過數、Media 狀態及處理速度。指定日期模式會從起始日期附近開始，抵達結束日期後立即停止。

## 輸出

完整歷史：

```text
exports/account_a/6450183261/logs/6450183261_2026-08.jsonl
```

指定日期範圍（即使跨月仍是單一檔案）：

```text
exports/account_a/6450183261/logs/6450183261_range_2026-07-20_2026-08-07.jsonl
```

媒體在兩種模式間共用，不會因重複匯出而建立副本：

```text
exports/account_a/6450183261/media/2026-08/854590.jpg
```

日期邊界及月份都以 `Asia/Taipei` 計算，指定日期的起訖日皆包含。重新執行相同匯出時會讀取既有 JSONL 的 `msg_id` 並略過，已存在且非空的媒體也會直接沿用。

## 歷史資料限制

歷史 API 提供訊息目前狀態，不保證能重建每次編輯前的舊文字或 reaction 的完整事件時間線。匯出內容包含目前文字、最後編輯時間、目前 reaction 彙總、回覆 ID、相簿 grouped ID 與媒體資訊。
