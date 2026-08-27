#!/usr/bin/env python3
"""Safely import Google Takeout Watch Later CSV into a YouTube playlist."""
import csv, json, os, random, sys, time
from datetime import datetime, timezone
from pathlib import Path
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

MAX_IMPORT_COUNT = None  # Full import; checkpoint resumes completed items.
PLAYLIST_TITLE = "Watch Later Archive 2026"
PLAYLIST_PRIVACY = "private"
SCOPES = ["https://www.googleapis.com/auth/youtube"]
BASE = Path(__file__).resolve().parent
CSV_FILE = BASE / "Watch later-videos.csv"
SECRET_FILE = BASE / "client_secret.json"
TOKEN_FILE = BASE / "youtube_token.json"
STATE_FILE = BASE / "youtube_import_state.json"
RESULT_FILE = BASE / "youtube_import_result.csv"
RETRYABLE = {429, 500, 502, 503, 504}
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg", "userRateLimitExceeded"}
MAX_RETRIES = 8
RESULT_LOCK_WARNING_SHOWN = False

class QuotaExhausted(Exception): pass
class SafeStop(Exception): pass

def now(): return datetime.now(timezone.utc).isoformat()

def atomic_json(path, data):
    fallback = path.with_name(path.name + ".tmp")
    writing = path.with_name(path.name + ".tmp.writing")
    with writing.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n"); f.flush(); os.fsync(f.fileno())
    for attempt in range(8):
        try:
            os.replace(writing, path)
            return
        except PermissionError:
            if attempt == 7:
                os.replace(writing, fallback)
                print(f"WARNING: {path.name} is locked. Latest valid checkpoint saved in {fallback.name} and will be recovered next run.", file=sys.stderr)
                return
            time.sleep(min(2.0, 0.1 * (2 ** attempt)))

def initial_state():
    return {"version": 1, "playlist_id": None, "playlist_title": PLAYLIST_TITLE,
            "channel_id": None, "channel_title": None, "completed_video_ids": [],
            "results": {}, "created_at": now(), "updated_at": now()}

def load_state():
    candidates = [p for p in (STATE_FILE, STATE_FILE.with_name(STATE_FILE.name + ".tmp")) if p.exists()]
    if not candidates: return initial_state()
    errors = []
    for candidate in sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        try:
            with candidate.open(encoding="utf-8") as f: state = json.load(f)
            if candidate != STATE_FILE:
                print(f"Recovering newer checkpoint from {candidate.name}.")
            state.setdefault("results", {})
            state["completed_video_ids"] = list(dict.fromkeys(state.get("completed_video_ids", [])))
            return state
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{candidate.name}: {error}")
    raise ValueError("No valid checkpoint found: " + "; ".join(errors))

def save(state):
    global RESULT_LOCK_WARNING_SHOWN
    state["completed_video_ids"] = list(dict.fromkeys(state["completed_video_ids"]))
    state["updated_at"] = now(); atomic_json(STATE_FILE, state)
    fields = ["video_id", "source_row", "source_timestamp", "status", "reason", "playlist_item_id", "updated_at"]
    tmp = RESULT_FILE.with_name(RESULT_FILE.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for result in state["results"].values(): w.writerow({k: result.get(k, "") for k in fields})
        f.flush(); os.fsync(f.fileno())
    try:
        os.replace(tmp, RESULT_FILE)
        RESULT_LOCK_WARNING_SHOWN = False
    except PermissionError:
        if not RESULT_LOCK_WARNING_SHOWN:
            print(f"WARNING: {RESULT_FILE.name} is locked (probably open in Excel). JSON checkpoint is safe; close the file and it will be regenerated on the next save.", file=sys.stderr)
            RESULT_LOCK_WARNING_SHOWN = True

def read_source():
    if not CSV_FILE.exists(): raise FileNotFoundError(CSV_FILE)
    with CSV_FILE.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        names = reader.fieldnames or []
        normalized = {x.strip().lower(): x for x in names if x}
        candidates = ["影片 id", "影片id", "video id", "video_id", "videoid"]
        id_col = next((normalized[x] for x in candidates if x in normalized), None)
        id_col = id_col or next((x for x in names if x and "影片" in x and "id" in x.lower()), None)
        if not id_col: raise ValueError(f"Cannot identify video ID column. Headers: {names}")
        ts_col = next((x for x in names if x and ("時間戳" in x or "timestamp" in x.lower())), None)
        rows, seen, raw_count = [], set(), 0
        for line, item in enumerate(reader, 2):
            raw_count += 1; video_id = (item.get(id_col) or "").strip()
            if not video_id or video_id in seen: continue
            seen.add(video_id)
            rows.append({"video_id": video_id, "source_row": str(line),
                         "source_timestamp": (item.get(ts_col) or "").strip() if ts_col else ""})
    return rows, id_col, ts_col, raw_count

def get_credentials():
    cred = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES) if TOKEN_FILE.exists() else None
    if cred and cred.expired and cred.refresh_token:
        try: cred.refresh(Request())
        except RefreshError as e: raise SafeStop(f"Token refresh failed: {e}. Delete {TOKEN_FILE.name} and run again.") from e
    if not cred or not cred.valid:
        if not SECRET_FILE.exists(): raise FileNotFoundError(SECRET_FILE)
        flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
        cred = flow.run_local_server(port=0, prompt="select_account", access_type="offline")
    TOKEN_FILE.write_text(cred.to_json(), encoding="utf-8")
    return cred

def error_info(error):
    status = int(getattr(error.resp, "status", 0) or 0); reasons = set(); message = str(error)
    try:
        data = json.loads(error.content.decode("utf-8"))["error"]
        message = data.get("message", message)
        reasons = {x.get("reason") for x in data.get("errors", []) if x.get("reason")}
    except (ValueError, KeyError, AttributeError, UnicodeDecodeError): pass
    return status, reasons, message

def api(factory, label):
    for attempt in range(MAX_RETRIES + 1):
        try: return factory().execute()
        except HttpError as error:
            status, reasons, message = error_info(error)
            if reasons & QUOTA_REASONS or (status == 403 and "quota" in message.lower()):
                raise QuotaExhausted(f"{label}: HTTP {status}: {message}") from error
            retryable = status in RETRYABLE or (status == 404 and "playlistNotFound" in reasons)
            if not retryable or attempt == MAX_RETRIES: raise
            delay = min(60, 2 ** attempt + random.random())
            print(f"Temporary HTTP {status} during {label}; retrying in {delay:.1f}s")
            time.sleep(delay)

def authenticated_channel(youtube):
    items = api(lambda: youtube.channels().list(part="snippet", mine=True, maxResults=50), "read channel").get("items", [])
    if len(items) != 1: raise SafeStop(f"Expected exactly one authenticated channel; received {len(items)}")
    return items[0]["id"], items[0]["snippet"]["title"]

def confirm_channel(channel_id, title):
    print(f"\n=== CHANNEL CONFIRMATION REQUIRED ===\nChannel name: {title}\nChannel ID:   {channel_id}")
    print("No playlist has been created and no video has been written in this run.")
    if input("Type the exact Channel ID to continue: ").strip() != channel_id:
        raise SafeStop(f"Channel not confirmed. If wrong, delete {TOKEN_FILE.name} and authorize again.")

def get_destination(youtube, state, channel_id, title):
    playlist_id = state.get("playlist_id")
    if playlist_id:
        if state.get("channel_id") != channel_id: raise SafeStop("Checkpoint belongs to another channel")
        items = api(lambda: youtube.playlists().list(part="snippet", id=playlist_id), "verify playlist").get("items", [])
        if not items: raise SafeStop(f"Saved playlist {playlist_id} unavailable; no replacement was created")
        if items[0]["snippet"].get("channelId") != channel_id: raise SafeStop("Saved playlist belongs to another channel")
        return playlist_id
    response = api(lambda: youtube.playlists().insert(part="snippet,status", body={
        "snippet": {"title": PLAYLIST_TITLE, "description": "Imported from Google Takeout Watch Later CSV."},
        "status": {"privacyStatus": PLAYLIST_PRIVACY}}), "create playlist")
    state.update({"playlist_id": response["id"], "playlist_title": PLAYLIST_TITLE,
                  "channel_id": channel_id, "channel_title": title}); save(state)
    return response["id"]

def reconcile(youtube, playlist_id, state, source_by_id):
    token, remote = None, set()
    while True:
        page = api(lambda token=token: youtube.playlistItems().list(
            part="contentDetails", playlistId=playlist_id, maxResults=50, pageToken=token), "reconcile playlist")
        remote.update(x.get("contentDetails", {}).get("videoId") for x in page.get("items", []))
        token = page.get("nextPageToken")
        if not token: break
    done, recovered = set(state["completed_video_ids"]), 0
    for video_id in remote:
        if video_id and video_id in source_by_id and video_id not in done:
            row = source_by_id[video_id]; state["completed_video_ids"].append(video_id); done.add(video_id); recovered += 1
            state["results"][video_id] = {**row, "status": "success_reconciled",
                "reason": "Already present in destination", "playlist_item_id": "", "updated_at": now()}
    if recovered: print(f"Recovered {recovered} completed remote insert(s)."); save(state)

def record_failure(state, row, reason):
    state["results"][row["video_id"]] = {**row, "status": "failed", "reason": reason,
        "playlist_item_id": "", "updated_at": now()}; save(state)

def terminal_failures(state):
    return {video_id for video_id, result in state["results"].items()
            if str(result.get("status", "")).startswith("failed")}

def preflight_available(youtube, state, pending):
    """Validate 50 IDs per 1-unit call and checkpoint both outcomes."""
    available = [row for row in pending if state["results"].get(row["video_id"], {}).get("status") == "validated_available"]
    unchecked = [row for row in pending if state["results"].get(row["video_id"], {}).get("status") != "validated_available"]
    for start in range(0, len(unchecked), 50):
        batch = unchecked[start:start + 50]
        ids = ",".join(row["video_id"] for row in batch)
        response = api(lambda ids=ids: youtube.videos().list(part="id,status", id=ids, maxResults=50), "preflight videos")
        visible = {item["id"] for item in response.get("items", [])}
        unavailable = 0
        for row in batch:
            video_id = row["video_id"]
            if video_id in visible:
                available.append(row)
                state["results"][video_id] = {**row, "status": "validated_available", "reason": "Visible in videos.list", "playlist_item_id": "", "updated_at": now()}
            else:
                state["results"][video_id] = {**row, "status": "failed_unavailable", "reason": "Not returned by videos.list: private, deleted, or unavailable", "playlist_item_id": "", "updated_at": now()}
                unavailable += 1
        if unavailable: print(f"Preflight batch: {unavailable} unavailable video(s) recorded; insert quota saved.")
        save(state)
    return available

def main():
    rows, id_col, ts_col, raw_count = read_source(); state = load_state(); done = set(state["completed_video_ids"])
    failed = terminal_failures(state)
    pending = [x for x in rows if x["video_id"] not in done and x["video_id"] not in failed]
    print(f"CSV: {CSV_FILE}\nID column: {id_col}\nTimestamp column: {ts_col or '(none)'}")
    print(f"CSV total rows: {raw_count}\nUnique valid videos: {len(rows)}\nCompleted: {len(done & {x['video_id'] for x in rows})}\nPending: {len(pending)}")
    print(f"This run limit: {MAX_IMPORT_COUNT if MAX_IMPORT_COUNT is not None else 'ALL'}")
    youtube = build("youtube", "v3", credentials=get_credentials(), cache_discovery=False)
    channel_id, title = authenticated_channel(youtube); confirm_channel(channel_id, title)
    playlist_id = get_destination(youtube, state, channel_id, title)
    print(f"Destination: https://www.youtube.com/playlist?list={playlist_id}")
    source_by_id = {x["video_id"]: x for x in rows}; reconcile(youtube, playlist_id, state, source_by_id)
    done = set(state["completed_video_ids"]); failed = terminal_failures(state)
    pending = [x for x in rows if x["video_id"] not in done and x["video_id"] not in failed]
    if MAX_IMPORT_COUNT is not None: pending = pending[:MAX_IMPORT_COUNT]
    print(f"Preflight checking {len(pending)} pending videos in batches of 50...")
    pending = preflight_available(youtube, state, pending)
    print(f"Preflight complete: {len(pending)} available videos remain for insertion.")
    for number, row in enumerate(pending, 1):
        video_id = row["video_id"]; print(f"[{number}/{len(pending)}] Importing {video_id}", flush=True)
        try:
            response = api(lambda video_id=video_id: youtube.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}), f"insert {video_id}")
        except QuotaExhausted: raise
        except HttpError as error:
            status, reasons, message = error_info(error)
            reason = f"HTTP {status}; reasons={','.join(sorted(reasons)) or 'unknown'}; {message}"
            if status in {401, 403}: raise SafeStop(reason) from error
            record_failure(state, row, reason); print(f"  Failed and recorded: {reason}"); continue
        state["completed_video_ids"].append(video_id)
        state["results"][video_id] = {**row, "status": "success", "reason": "",
            "playlist_item_id": response.get("id", ""), "updated_at": now()}; save(state)
    failed = terminal_failures(state)
    remaining = sum(x["video_id"] not in set(state["completed_video_ids"]) and x["video_id"] not in failed for x in rows)
    print(f"Finished safely. Completed={len(state['completed_video_ids'])}; pending={remaining}; permanently failed={len(failed)}")
    print(f"Result: {RESULT_FILE}\nOriginal Watch Later was not modified.")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: print("\nCtrl+C: stopped safely; run again to resume.", file=sys.stderr); raise SystemExit(130)
    except QuotaExhausted as e: print(f"\nQuota exhausted; stopped safely. Retry after reset.\n{e}", file=sys.stderr); raise SystemExit(75)
    except SafeStop as e: print(f"\nStopped safely: {e}", file=sys.stderr); raise SystemExit(2)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e: print(f"\nInput/configuration error: {e}", file=sys.stderr); raise SystemExit(2)
