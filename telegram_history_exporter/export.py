from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import re
import sys
import time as monotonic_time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageMediaContact,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
    MessageMediaPoll,
    MessageMediaVenue,
    MessageMediaWebPage,
)


APP_DIR = Path(__file__).resolve().parent
ACCOUNTS_DIR = APP_DIR / "accounts"
SESSIONS_DIR = APP_DIR / "sessions"
EXPORTS_DIR = APP_DIR / "exports"
LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Taipei")


@dataclass(frozen=True)
class ExportRange:
    start: datetime | None
    end_exclusive: datetime | None
    label: str | None

    def contains(self, value: datetime) -> bool:
        local = ensure_aware(value).astimezone(LOCAL_TZ)
        if self.start is not None and local < self.start:
            return False
        if self.end_exclusive is not None and local >= self.end_exclusive:
            return False
        return True


@dataclass
class ExportStats:
    scanned: int = 0
    exported: int = 0
    skipped: int = 0
    media_complete: int = 0
    media_existing: int = 0
    media_failed: int = 0
    started_at: float = 0.0
    last_progress_at: float = 0.0

    def __post_init__(self) -> None:
        now = monotonic_time.monotonic()
        self.started_at = now
        self.last_progress_at = now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one Telegram chat to JSONL, with shared media files."
    )
    parser.add_argument("--account", help="Account env name, e.g. account_a")
    parser.add_argument("--chat-id", type=int, help="Telegram chat/user/channel ID")
    parser.add_argument("--from-date", type=parse_iso_date, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--to-date", type=parse_iso_date, help="Inclusive YYYY-MM-DD")
    parser.add_argument(
        "--no-media", action="store_true", help="Write metadata but do not download media"
    )
    parser.add_argument(
        "--media-workers",
        type=positive_int,
        default=3,
        help="Concurrent media downloads (default: 3)",
    )
    parser.add_argument(
        "--media-timeout",
        type=positive_int,
        default=120,
        help="Timeout in seconds for one media attempt (default: 120)",
    )
    parser.add_argument(
        "--media-retries",
        type=non_negative_int,
        default=2,
        help="Retries after the first media attempt (default: 2)",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must be YYYY-MM-DD") from exc


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be at least 1")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value cannot be negative")
    return parsed


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def prompt_missing(args: argparse.Namespace) -> argparse.Namespace:
    if not args.account:
        args.account = prompt_account()
    if not args.chat_id:
        args.chat_id = int(input("Chat ID: ").strip())

    if args.from_date or args.to_date:
        if not (args.from_date and args.to_date):
            raise SystemExit("--from-date 與 --to-date 必須一起提供。")
        return args

    print("\n匯出模式：\n1. 全部歷史（LOG 依月份分檔）\n2. 指定日期範圍（單一 LOG）")
    mode = input("請選擇 [1/2]: ").strip() or "1"
    if mode == "2":
        args.from_date = prompt_date("起始日期 YYYY-MM-DD: ")
        args.to_date = prompt_date("結束日期 YYYY-MM-DD: ")
    elif mode != "1":
        raise SystemExit("匯出模式只能選擇 1 或 2。")
    return args


def discover_accounts(accounts_dir: Path = ACCOUNTS_DIR) -> list[str]:
    if not accounts_dir.is_dir():
        return []
    return sorted(
        path.stem
        for path in accounts_dir.glob("*.env")
        if path.name.lower() != "example.env"
        and re.fullmatch(r"[A-Za-z0-9_-]+", path.stem)
    )


def prompt_account() -> str:
    accounts = discover_accounts()
    if not accounts:
        raise SystemExit(
            f"找不到帳號設定。請先將 {ACCOUNTS_DIR / 'example.env'} 複製為 "
            f"{ACCOUNTS_DIR / 'account_a.env'} 並填入帳號資料。"
        )
    print("\n偵測到以下帳號設定：")
    for index, account in enumerate(accounts, start=1):
        print(f"{index}. {account}")
    while True:
        raw = input(f"請選擇帳號 [1-{len(accounts)}]: ").strip()
        try:
            selected = int(raw)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(accounts):
            return accounts[selected - 1]
        print("選擇無效，請輸入選單中的數字。")


def prompt_date(label: str) -> date:
    while True:
        raw = input(label).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print("日期格式錯誤，請使用 YYYY-MM-DD。")


def build_range(start: date | None, end: date | None) -> ExportRange:
    if start is None and end is None:
        return ExportRange(None, None, None)
    if start is None or end is None:
        raise ValueError("Start and end dates must be provided together")
    if start > end:
        raise ValueError("起始日期不可晚於結束日期。")
    start_dt = datetime.combine(start, time.min, LOCAL_TZ)
    # A strict exclusive bound avoids microsecond boundary mistakes.
    end_exclusive = datetime.combine(end, time.min, LOCAL_TZ) + timedelta(days=1)
    return ExportRange(start_dt, end_exclusive, f"range_{start.isoformat()}_{end.isoformat()}")


def load_account(name: str) -> tuple[int, str, str | None, Path]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise SystemExit("Account 名稱只能包含英數字、底線與連字號。")
    env_path = ACCOUNTS_DIR / f"{name}.env"
    if not env_path.is_file():
        raise SystemExit(f"找不到帳號設定：{env_path}")
    config = dotenv_values(env_path)
    try:
        api_id = int(str(config["TG_API_ID"]))
        api_hash = str(config["TG_API_HASH"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"{env_path} 缺少有效的 TG_API_ID/TG_API_HASH。") from exc
    phone = str(config.get("TG_PHONE") or "").strip() or None
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return api_id, api_hash, phone, SESSIONS_DIR / name


async def resolve_chat(client: TelegramClient, requested_id: int) -> Any:
    candidates = {requested_id, abs(requested_id)}
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        raw_id = getattr(entity, "id", None)
        marked_id = utils.get_peer_id(entity)
        if raw_id in candidates or marked_id == requested_id:
            return entity
    try:
        return await client.get_entity(requested_id)
    except (ValueError, TypeError) as exc:
        raise SystemExit(
            f"無法解析 chat_id={requested_id}。請確認此帳號的對話清單中仍有該對話。"
        ) from exc


async def start_user_client(client: TelegramClient, phone: str | None) -> None:
    if phone:
        await client.start(phone=phone)
    else:
        # Omitting the argument lets Telethon prompt for a phone number.
        await client.start()


def entity_name(entity: Any) -> str:
    return utils.get_display_name(entity) or getattr(entity, "username", None) or "Unknown"


def sender_fields(sender: Any) -> tuple[str | None, int | None]:
    if sender is None:
        return None, None
    username = getattr(sender, "username", None)
    display = username or utils.get_display_name(sender) or None
    return display, getattr(sender, "id", None)


def reaction_data(message: Any) -> list[dict[str, Any]]:
    reactions = getattr(message, "reactions", None)
    output: list[dict[str, Any]] = []
    for item in getattr(reactions, "results", None) or []:
        reaction = getattr(item, "reaction", None)
        emoji = getattr(reaction, "emoticon", None)
        document_id = getattr(reaction, "document_id", None)
        output.append(
            {
                "emoji": emoji,
                "custom_emoji_id": document_id,
                "count": getattr(item, "count", 0),
                "chosen_by_me": bool(getattr(item, "chosen_order", None) is not None),
            }
        )
    return output


def classify_document(document: Any) -> str:
    attrs = getattr(document, "attributes", None) or []
    for attr in attrs:
        name = type(attr).__name__
        if name == "DocumentAttributeSticker":
            return "sticker"
        if name == "DocumentAttributeAnimated":
            return "animation"
        if name == "DocumentAttributeAudio":
            return "voice" if getattr(attr, "voice", False) else "audio"
        if name == "DocumentAttributeVideo":
            return "video_note" if getattr(attr, "round_message", False) else "video"
    return "document"


def media_type(message: Any) -> str | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        return classify_document(media.document)
    if isinstance(media, MessageMediaContact):
        return "contact"
    if isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
        return "location"
    if isinstance(media, MessageMediaVenue):
        return "venue"
    if isinstance(media, MessageMediaPoll):
        return "poll"
    if isinstance(media, MessageMediaWebPage):
        return "webpage"
    return type(media).__name__.removeprefix("MessageMedia").lower()


def safe_extension(message: Any) -> str:
    ext = getattr(getattr(message, "file", None), "ext", None)
    if ext and re.fullmatch(r"\.[A-Za-z0-9]{1,10}", ext):
        return ext.lower()
    mime = getattr(getattr(message, "file", None), "mime_type", None)
    guessed = mimetypes.guess_extension(mime or "")
    return guessed or ".bin"


def media_metadata(message: Any) -> dict[str, Any] | None:
    kind = media_type(message)
    if kind is None:
        return None
    file = getattr(message, "file", None)
    media = getattr(message, "media", None)
    result: dict[str, Any] = {
        "type": kind,
        "file_path": None,
        "file_name": getattr(file, "name", None),
        "mime_type": getattr(file, "mime_type", None),
        "size": getattr(file, "size", None),
        "width": getattr(file, "width", None),
        "height": getattr(file, "height", None),
        "duration": getattr(file, "duration", None),
        "download_status": "not_applicable" if file is None else "pending",
    }
    if kind == "contact":
        result["contact"] = {
            "phone_number": getattr(media, "phone_number", None),
            "first_name": getattr(media, "first_name", None),
            "last_name": getattr(media, "last_name", None),
            "user_id": getattr(media, "user_id", None),
        }
    elif kind in {"location", "venue"}:
        geo = getattr(media, "geo", None)
        result["location"] = {
            "latitude": getattr(geo, "lat", None),
            "longitude": getattr(geo, "long", None),
            "title": getattr(media, "title", None),
            "address": getattr(media, "address", None),
        }
    elif kind == "poll":
        poll = getattr(media, "poll", None)
        result["poll"] = {
            "id": getattr(poll, "id", None),
            "question": getattr(getattr(poll, "question", None), "text", None),
        }
    return result


async def download_media(
    message: Any,
    metadata: dict[str, Any],
    media_root: Path,
    local_date: date,
    semaphore: asyncio.Semaphore,
    timeout_seconds: int,
    retries: int,
) -> None:
    if getattr(message, "file", None) is None:
        return
    month_dir = media_root / local_date.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    destination = month_dir / f"{message.id}{safe_extension(message)}"
    relative = destination.relative_to(media_root.parent).as_posix()
    metadata["file_path"] = relative
    metadata["stored_file_name"] = destination.name
    if destination.is_file() and destination.stat().st_size > 0:
        metadata["download_status"] = "existing"
        return

    temporary = destination.with_name(destination.name + ".part")
    attempts = retries + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        if temporary.exists():
            temporary.unlink()
        print(
            f"[Media] msg_id={message.id} {metadata['type']} "
            f"嘗試 {attempt}/{attempts}: {destination.name}"
        )
        try:
            async with semaphore:
                downloaded = await asyncio.wait_for(
                    message.download_media(file=str(temporary)),
                    timeout=timeout_seconds,
                )
            actual = Path(downloaded) if downloaded else temporary
            if actual != temporary and actual.exists():
                temporary = actual
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise OSError("Telegram 未回傳有效媒體檔案")
            os.replace(temporary, destination)
            metadata["download_status"] = "complete"
            metadata["size_on_disk"] = destination.stat().st_size
            print(f"[Media] 完成 msg_id={message.id}: {destination.name}")
            return
        except FloodWaitError:
            raise
        except Exception as exc:  # Retry one bad media item without stopping the export.
            last_error = exc
            if attempt < attempts:
                print(f"[Media] 失敗，稍後重試 msg_id={message.id}: {type(exc).__name__}")
                await asyncio.sleep(min(2**attempt, 10))

    metadata["download_status"] = "failed"
    metadata["error"] = f"{type(last_error).__name__}: {last_error}"
    print(f"[Media] 已略過 msg_id={message.id}: {metadata['error']}")


def log_path(
    log_root: Path, chat_id: int, export_range: ExportRange, local_date: date
) -> Path:
    if export_range.label:
        return log_root / f"{chat_id}_{export_range.label}.jsonl"
    return log_root / f"{chat_id}_{local_date:%Y-%m}.jsonl"


def read_existing_ids(path: Path) -> set[int]:
    ids: set[int] = set()
    if not path.is_file():
        return ids
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
                if value.get("event_type") in {"message", "service"}:
                    ids.add(int(value["msg_id"]))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return ids


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        stream.write("\n")


def show_progress(stats: ExportStats, current_time: datetime, force: bool = False) -> None:
    now = monotonic_time.monotonic()
    if not force and now - stats.last_progress_at < 5:
        return
    elapsed = max(now - stats.started_at, 0.001)
    rate = stats.scanned / elapsed
    print(
        f"[進度] 日期={current_time:%Y-%m-%d %H:%M:%S} "
        f"掃描={stats.scanned} 新增={stats.exported} 略過={stats.skipped} "
        f"Media完成={stats.media_complete} 沿用={stats.media_existing} "
        f"失敗={stats.media_failed} 速度={rate:.1f}則/秒"
    )
    stats.last_progress_at = now


async def build_record(
    message: Any,
    args: argparse.Namespace,
    chat_name: str,
    media_root: Path,
    local_time: datetime,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    sender = message.sender
    if sender is None:
        try:
            sender = await message.get_sender()
        except Exception:
            sender = None
    sender_name, sender_id = sender_fields(sender)
    metadata = media_metadata(message)
    if metadata and not args.no_media:
        await download_media(
            message,
            metadata,
            media_root,
            local_time.date(),
            semaphore,
            args.media_timeout,
            args.media_retries,
        )
    elif metadata and metadata["download_status"] == "pending":
        metadata["download_status"] = "skipped"

    event_type = "service" if getattr(message, "action", None) else "message"
    return {
        "time": local_time.isoformat(),
        "msg_id": message.id,
        "chat_id": args.chat_id,
        "chat_name": chat_name,
        "user": sender_name,
        "user_id": sender_id,
        "text": message.message or "",
        "reply_id": getattr(message, "reply_to_msg_id", None),
        "is_edit": message.edit_date is not None,
        "edit_time": (
            ensure_aware(message.edit_date).astimezone(LOCAL_TZ).isoformat()
            if message.edit_date
            else None
        ),
        "event_type": event_type,
        "grouped_id": getattr(message, "grouped_id", None),
        "reactions": reaction_data(message),
        "media": metadata,
    }


async def flush_batch(
    batch: list[tuple[Any, datetime, Path, set[int]]],
    args: argparse.Namespace,
    chat_name: str,
    media_root: Path,
    semaphore: asyncio.Semaphore,
    stats: ExportStats,
) -> None:
    if not batch:
        return
    records = await asyncio.gather(
        *(
            build_record(message, args, chat_name, media_root, local_time, semaphore)
            for message, local_time, _, _ in batch
        )
    )
    for (message, _, destination_log, known_ids), record in zip(batch, records):
        append_jsonl(destination_log, record)
        known_ids.add(message.id)
        stats.exported += 1
        status = (record.get("media") or {}).get("download_status")
        if status == "complete":
            stats.media_complete += 1
        elif status == "existing":
            stats.media_existing += 1
        elif status == "failed":
            stats.media_failed += 1
    batch.clear()


async def export_chat(args: argparse.Namespace) -> None:
    export_range = build_range(args.from_date, args.to_date)
    api_id, api_hash, phone, session = load_account(args.account)
    client = TelegramClient(str(session), api_id, api_hash, flood_sleep_threshold=60)
    await start_user_client(client, phone)
    try:
        entity = await resolve_chat(client, args.chat_id)
        canonical_id = getattr(entity, "id", args.chat_id)
        account_root = EXPORTS_DIR / args.account / str(args.chat_id)
        log_root = account_root / "logs"
        media_root = account_root / "media"
        chat_name = entity_name(entity)
        print(f"開始匯出：{chat_name} (chat_id={canonical_id})")

        existing_by_path: dict[Path, set[int]] = {}
        stats = ExportStats()
        semaphore = asyncio.Semaphore(args.media_workers)
        batch: list[tuple[Any, datetime, Path, set[int]]] = []
        iterator_options: dict[str, Any] = {"reverse": True}
        if export_range.start is not None:
            # reverse=True reverses offset_date too. One second of overlap keeps
            # messages exactly on the inclusive local start boundary.
            iterator_options["offset_date"] = (
                export_range.start.astimezone(timezone.utc) - timedelta(seconds=1)
            )

        async for message in client.iter_messages(entity, **iterator_options):
            if not message.date:
                continue
            local_time = ensure_aware(message.date).astimezone(LOCAL_TZ)
            if export_range.end_exclusive and local_time >= export_range.end_exclusive:
                break
            stats.scanned += 1
            show_progress(stats, local_time)
            if not export_range.contains(message.date):
                continue
            destination_log = log_path(
                log_root, args.chat_id, export_range, local_time.date()
            )
            known_ids = existing_by_path.setdefault(
                destination_log, read_existing_ids(destination_log)
            )
            if message.id in known_ids:
                stats.skipped += 1
                continue
            batch.append((message, local_time, destination_log, known_ids))
            if len(batch) >= max(args.media_workers * 2, 10):
                await flush_batch(
                    batch, args, chat_name, media_root, semaphore, stats
                )
                show_progress(stats, local_time, force=True)

        await flush_batch(batch, args, chat_name, media_root, semaphore, stats)
        final_time = local_time if "local_time" in locals() else datetime.now(LOCAL_TZ)
        show_progress(stats, final_time, force=True)

        print(
            f"完成：新增 {stats.exported} 則、略過既有 {stats.skipped} 則、"
            f"媒體完成 {stats.media_complete}、沿用 {stats.media_existing}、"
            f"失敗 {stats.media_failed}。輸出：{account_root}"
        )
    except FloodWaitError as exc:
        raise SystemExit(f"Telegram 要求等待 {exc.seconds} 秒，稍後重跑即可續傳。") from exc
    finally:
        await client.disconnect()


def main() -> None:
    args = prompt_missing(parse_args())
    try:
        asyncio.run(export_chat(args))
    except KeyboardInterrupt:
        print("\n已中止；下次使用相同參數可略過既有訊息並繼續。")
        sys.exit(130)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
