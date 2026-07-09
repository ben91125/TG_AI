from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StoredMessage:
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
    is_game_list_related: bool
    game_list_reason: str
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

            CREATE TABLE IF NOT EXISTS messages (
                message_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_id INTEGER,
                text TEXT NOT NULL,
                reply_to_message_id INTEGER,
                created_at TEXT NOT NULL,
                is_game_list_related INTEGER NOT NULL,
                game_list_reason TEXT NOT NULL,
                quality_score INTEGER NOT NULL,
                quality_reason TEXT NOT NULL,
                UNIQUE(chat_id, message_id)
            );
            """
        )
        self.conn.commit()

    def upsert_message(self, message: StoredMessage) -> None:
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
            INSERT INTO messages (
                chat_id,
                message_id,
                sender_id,
                text,
                reply_to_message_id,
                created_at,
                is_game_list_related,
                game_list_reason,
                quality_score,
                quality_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                sender_id = excluded.sender_id,
                text = excluded.text,
                reply_to_message_id = excluded.reply_to_message_id,
                created_at = excluded.created_at,
                is_game_list_related = excluded.is_game_list_related,
                game_list_reason = excluded.game_list_reason,
                quality_score = excluded.quality_score,
                quality_reason = excluded.quality_reason
            """,
            (
                message.chat_id,
                message.message_id,
                message.sender_id,
                message.text,
                message.reply_to_message_id,
                message.created_at,
                int(message.is_game_list_related),
                message.game_list_reason,
                message.quality_score,
                message.quality_reason,
            ),
        )
        self.conn.commit()

    def tracked_user_summary(self, tracked_user_ids: set[int]) -> list[sqlite3.Row]:
        if not tracked_user_ids:
            return []

        placeholders = ", ".join("?" for _ in tracked_user_ids)
        query = f"""
            SELECT
                sender_id AS user_id,
                COUNT(*) AS reply_count,
                ROUND(AVG(quality_score), 2) AS avg_quality_score,
                SUM(CASE WHEN quality_score >= 70 THEN 1 ELSE 0 END) AS high_quality_replies,
                SUM(CASE WHEN is_game_list_related = 1 THEN 1 ELSE 0 END) AS game_list_related_replies
            FROM messages
            WHERE sender_id IN ({placeholders})
              AND reply_to_message_id IS NOT NULL
            GROUP BY sender_id
            ORDER BY reply_count DESC, avg_quality_score DESC
        """
        cursor = self.conn.execute(query, tuple(tracked_user_ids))
        return cursor.fetchall()

    def close(self) -> None:
        self.conn.close()

