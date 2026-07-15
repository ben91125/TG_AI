from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    api_id: int
    api_hash: str
    session_name: str
    tracked_user_ids: set[int]
    chat_blocklist_ids: set[int]
    auto_mark_read: bool
    auto_mark_read_delay_min_seconds: float
    auto_mark_read_delay_max_seconds: float
    sqlite_path: Path
    log_level: str


def _parse_int_set(raw_value: str) -> set[int]:
    values = set()
    for chunk in raw_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        values.add(int(chunk))
    return values


def _parse_bool(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_delay_seconds(raw_value: str, env_name: str) -> float:
    try:
        value = float(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a number") from exc

    if value < 0:
        raise ValueError(f"{env_name} must not be negative")
    return value


def load_settings() -> Settings:
    load_dotenv()

    api_id_raw = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    session_name = os.getenv("TG_SESSION_NAME", "tg-ai-monitor").strip()
    tracked_user_ids_raw = os.getenv("TRACKED_USER_IDS", "")
    chat_blocklist_ids_raw = os.getenv("CHAT_BLOCKLIST_IDS", "")
    auto_mark_read = _parse_bool(os.getenv("AUTO_MARK_READ", "false"))
    auto_mark_read_delay_min_seconds = _parse_delay_seconds(
        os.getenv("AUTO_MARK_READ_DELAY_MIN_SECONDS", "0"),
        "AUTO_MARK_READ_DELAY_MIN_SECONDS",
    )
    auto_mark_read_delay_max_seconds = _parse_delay_seconds(
        os.getenv("AUTO_MARK_READ_DELAY_MAX_SECONDS", "60"),
        "AUTO_MARK_READ_DELAY_MAX_SECONDS",
    )
    sqlite_path = Path(os.getenv("SQLITE_PATH", "data/tg_monitor.db")).expanduser()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper().strip()

    missing = []
    if not api_id_raw:
        missing.append("TG_API_ID")
    if not api_hash:
        missing.append("TG_API_HASH")
    if missing:
        raise ValueError(f"Missing required environment values: {', '.join(missing)}")
    if auto_mark_read_delay_min_seconds > auto_mark_read_delay_max_seconds:
        raise ValueError(
            "AUTO_MARK_READ_DELAY_MIN_SECONDS must be less than or equal to "
            "AUTO_MARK_READ_DELAY_MAX_SECONDS"
        )

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        api_id=int(api_id_raw),
        api_hash=api_hash,
        session_name=session_name,
        tracked_user_ids=_parse_int_set(tracked_user_ids_raw),
        chat_blocklist_ids=_parse_int_set(chat_blocklist_ids_raw),
        auto_mark_read=auto_mark_read,
        auto_mark_read_delay_min_seconds=auto_mark_read_delay_min_seconds,
        auto_mark_read_delay_max_seconds=auto_mark_read_delay_max_seconds,
        sqlite_path=sqlite_path,
        log_level=log_level,
    )
