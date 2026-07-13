from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class RawMessage:
    chat_id: int
    chat_title: str | None
    chat_username: str | None
    sender_id: int | None
    sender_username: str | None
    sender_display_name: str | None
    message_id: int
    text: str
    reply_to_message_id: int | None
    created_at: str
    edited_at: str | None


@dataclass(slots=True)
class GameListAnalysis:
    chat_id: int
    message_id: int
    is_related: bool
    reason: str


@dataclass(slots=True)
class UserReplyAnalysis:
    chat_id: int
    message_id: int
    user_id: int | None
    is_reply: bool
    response_type: str
    response_type_reason: str
    quality_score: int
    quality_reason: str


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_messages (
                raw_message_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_id INTEGER,
                text TEXT NOT NULL,
                reply_to_message_id INTEGER,
                created_at TEXT NOT NULL,
                edited_at TEXT,
                edit_count INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS game_list_analysis (
                analysis_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                is_related INTEGER NOT NULL,
                reason TEXT NOT NULL,
                analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS user_reply_analysis (
                analysis_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER,
                is_reply INTEGER NOT NULL,
                response_type TEXT NOT NULL,
                response_type_reason TEXT NOT NULL,
                quality_score INTEGER NOT NULL,
                quality_reason TEXT NOT NULL,
                analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, message_id)
            );
            """
        )
        self._ensure_raw_message_columns()
        self._migrate_legacy_messages()
        self.conn.commit()

    def _ensure_raw_message_columns(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(raw_messages)").fetchall()}
        if "edited_at" not in columns:
            self.conn.execute("ALTER TABLE raw_messages ADD COLUMN edited_at TEXT")
        if "edit_count" not in columns:
            self.conn.execute("ALTER TABLE raw_messages ADD COLUMN edit_count INTEGER NOT NULL DEFAULT 0")
        if "last_seen_at" not in columns:
            self.conn.execute("ALTER TABLE raw_messages ADD COLUMN last_seen_at TEXT")
        self.conn.execute(
            """
            UPDATE raw_messages
            SET last_seen_at = created_at
            WHERE last_seen_at IS NULL
            """
        )

    def _migrate_legacy_messages(self) -> None:
        if not self._table_exists("messages"):
            return

        self.conn.executescript(
            """
            INSERT OR IGNORE INTO raw_messages (
                chat_id,
                message_id,
                sender_id,
                text,
                reply_to_message_id,
                created_at,
                edited_at,
                edit_count,
                last_seen_at
            )
            SELECT
                chat_id,
                message_id,
                sender_id,
                text,
                reply_to_message_id,
                created_at,
                NULL,
                0,
                created_at
            FROM messages;

            INSERT OR IGNORE INTO game_list_analysis (
                chat_id,
                message_id,
                is_related,
                reason
            )
            SELECT
                chat_id,
                message_id,
                is_game_list_related,
                game_list_reason
            FROM messages;

            INSERT OR IGNORE INTO user_reply_analysis (
                chat_id,
                message_id,
                user_id,
                is_reply,
                response_type,
                response_type_reason,
                quality_score,
                quality_reason
            )
            SELECT
                chat_id,
                message_id,
                sender_id,
                CASE WHEN reply_to_message_id IS NULL THEN 0 ELSE 1 END,
                'legacy',
                'migrated from old messages table',
                quality_score,
                quality_reason
            FROM messages;
            """
        )

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    def upsert_raw_message(self, message: RawMessage) -> bool:
        existing = self.conn.execute(
            """
            SELECT text
            FROM raw_messages
            WHERE chat_id = ?
              AND message_id = ?
            """,
            (message.chat_id, message.message_id),
        ).fetchone()
        text_changed = existing is not None and existing["text"] != message.text
        last_seen_at = _utc_now_iso()

        self.conn.execute(
            """
            INSERT INTO chats (chat_id, title, username)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username
            """,
            (message.chat_id, message.chat_title, message.chat_username),
        )

        if message.sender_id is not None:
            self.conn.execute(
                """
                INSERT INTO users (user_id, username, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name
                """,
                (message.sender_id, message.sender_username, message.sender_display_name),
            )

        self.conn.execute(
            """
            INSERT INTO raw_messages (
                chat_id,
                message_id,
                sender_id,
                text,
                reply_to_message_id,
                created_at,
                edited_at,
                edit_count,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                sender_id = excluded.sender_id,
                text = excluded.text,
                reply_to_message_id = excluded.reply_to_message_id,
                created_at = excluded.created_at,
                edited_at = CASE
                    WHEN raw_messages.text IS NOT excluded.text
                    THEN COALESCE(excluded.edited_at, excluded.last_seen_at)
                    ELSE COALESCE(excluded.edited_at, raw_messages.edited_at)
                END,
                edit_count = CASE
                    WHEN raw_messages.text IS NOT excluded.text
                    THEN raw_messages.edit_count + 1
                    ELSE raw_messages.edit_count
                END,
                last_seen_at = excluded.last_seen_at
            """,
            (
                message.chat_id,
                message.message_id,
                message.sender_id,
                message.text,
                message.reply_to_message_id,
                message.created_at,
                message.edited_at,
                last_seen_at,
            ),
        )
        self.conn.commit()
        return text_changed

    def upsert_game_list_analysis(self, analysis: GameListAnalysis) -> None:
        self.conn.execute(
            """
            INSERT INTO game_list_analysis (
                chat_id,
                message_id,
                is_related,
                reason
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                is_related = excluded.is_related,
                reason = excluded.reason,
                analyzed_at = CURRENT_TIMESTAMP
            """,
            (
                analysis.chat_id,
                analysis.message_id,
                int(analysis.is_related),
                analysis.reason,
            ),
        )
        self.conn.commit()

    def upsert_user_reply_analysis(self, analysis: UserReplyAnalysis) -> None:
        self.conn.execute(
            """
            INSERT INTO user_reply_analysis (
                chat_id,
                message_id,
                user_id,
                is_reply,
                response_type,
                response_type_reason,
                quality_score,
                quality_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                user_id = excluded.user_id,
                is_reply = excluded.is_reply,
                response_type = excluded.response_type,
                response_type_reason = excluded.response_type_reason,
                quality_score = excluded.quality_score,
                quality_reason = excluded.quality_reason,
                analyzed_at = CURRENT_TIMESTAMP
            """,
            (
                analysis.chat_id,
                analysis.message_id,
                analysis.user_id,
                int(analysis.is_reply),
                analysis.response_type,
                analysis.response_type_reason,
                analysis.quality_score,
                analysis.quality_reason,
            ),
        )
        self.conn.commit()

    def tracked_user_summary(self, tracked_user_ids: set[int]) -> list[sqlite3.Row]:
        if not tracked_user_ids:
            return []

        placeholders = ", ".join("?" for _ in tracked_user_ids)
        query = f"""
            SELECT
                ura.user_id AS user_id,
                COUNT(*) AS reply_count,
                ROUND(AVG(ura.quality_score), 2) AS avg_quality_score,
                SUM(CASE WHEN ura.quality_score >= 70 THEN 1 ELSE 0 END) AS high_quality_replies,
                SUM(CASE WHEN ura.quality_score < 40 THEN 1 ELSE 0 END) AS low_quality_replies
            FROM user_reply_analysis ura
            WHERE ura.user_id IN ({placeholders})
              AND ura.is_reply = 1
            GROUP BY ura.user_id
            ORDER BY reply_count DESC, avg_quality_score DESC
        """
        cursor = self.conn.execute(query, tuple(tracked_user_ids))
        return cursor.fetchall()

    def close(self) -> None:
        self.conn.close()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
