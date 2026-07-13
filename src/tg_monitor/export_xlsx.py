from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import load_settings
from .storage import SQLiteStore

LOCAL_TZ = timezone(timedelta(hours=8))


def main() -> None:
    settings = load_settings()
    output_dir = Path("outputs/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"tg_monitor_snapshot_{datetime.now(LOCAL_TZ):%Y%m%d_%H%M%S}.xlsx"

    store = SQLiteStore(settings.sqlite_path)
    try:
        workbook = Workbook()
        workbook.remove(workbook.active)

        _add_query_sheet(
            workbook,
            "RawMessages",
            store,
            """
            SELECT
                rm.created_at,
                c.title AS chat_title,
                rm.chat_id,
                u.display_name AS sender_name,
                u.username AS sender_username,
                rm.sender_id,
                rm.message_id,
                rm.reply_to_message_id,
                rm.edited_at,
                rm.edit_count,
                rm.last_seen_at,
                rm.text
            FROM raw_messages rm
            LEFT JOIN chats c ON c.chat_id = rm.chat_id
            LEFT JOIN users u ON u.user_id = rm.sender_id
            ORDER BY rm.created_at DESC, rm.raw_message_pk DESC
            """,
        )
        _add_query_sheet(
            workbook,
            "GameListAnalysis",
            store,
            """
            SELECT
                rm.created_at,
                c.title AS chat_title,
                gla.chat_id,
                gla.message_id,
                gla.is_related,
                gla.reason,
                rm.edited_at,
                rm.edit_count,
                rm.last_seen_at,
                rm.text
            FROM game_list_analysis gla
            JOIN raw_messages rm
              ON rm.chat_id = gla.chat_id
             AND rm.message_id = gla.message_id
            LEFT JOIN chats c ON c.chat_id = gla.chat_id
            ORDER BY rm.created_at DESC, gla.analysis_pk DESC
            """,
        )
        _add_query_sheet(
            workbook,
            "UserReview",
            store,
            """
            SELECT
                rm.created_at,
                c.title AS chat_title,
                ura.user_id,
                u.display_name AS sender_name,
                u.username AS sender_username,
                ura.is_reply,
                ura.response_type,
                ura.response_type_reason,
                ura.quality_score,
                ura.quality_reason,
                rm.edited_at,
                rm.edit_count,
                rm.last_seen_at,
                rm.text
            FROM user_reply_analysis ura
            JOIN raw_messages rm
              ON rm.chat_id = ura.chat_id
             AND rm.message_id = ura.message_id
            LEFT JOIN chats c ON c.chat_id = ura.chat_id
            LEFT JOIN users u ON u.user_id = ura.user_id
            ORDER BY rm.created_at DESC, ura.analysis_pk DESC
            """,
        )
        _add_query_sheet(
            workbook,
            "Chats",
            store,
            """
            SELECT
                c.chat_id,
                c.title,
                c.username,
                COUNT(rm.raw_message_pk) AS message_count,
                MAX(rm.created_at) AS latest_message_at
            FROM chats c
            LEFT JOIN raw_messages rm ON rm.chat_id = c.chat_id
            GROUP BY c.chat_id, c.title, c.username
            ORDER BY latest_message_at DESC
            """,
        )
        _add_query_sheet(
            workbook,
            "Users",
            store,
            """
            SELECT
                u.user_id,
                u.display_name,
                u.username,
                COUNT(rm.raw_message_pk) AS message_count,
                MAX(rm.created_at) AS latest_message_at
            FROM users u
            LEFT JOIN raw_messages rm ON rm.sender_id = u.user_id
            GROUP BY u.user_id, u.display_name, u.username
            ORDER BY latest_message_at DESC
            """,
        )

        workbook.save(output_path)
        print(output_path)
    finally:
        store.close()


def _add_query_sheet(workbook: Workbook, title: str, store: SQLiteStore, query: str) -> None:
    rows = store.conn.execute(query).fetchall()
    sheet = workbook.create_sheet(title=title)

    headers = rows[0].keys() if rows else _empty_headers_for(title)
    sheet.append(list(headers))
    for row in rows:
        sheet.append([row[header] for header in headers])

    _style_sheet(sheet)


def _empty_headers_for(title: str) -> list[str]:
    headers_by_title = {
        "RawMessages": [
            "created_at",
            "chat_title",
            "chat_id",
            "sender_name",
            "sender_username",
            "sender_id",
            "message_id",
            "reply_to_message_id",
            "edited_at",
            "edit_count",
            "last_seen_at",
            "text",
        ],
        "GameListAnalysis": [
            "created_at",
            "chat_title",
            "chat_id",
            "message_id",
            "is_related",
            "reason",
            "edited_at",
            "edit_count",
            "last_seen_at",
            "text",
        ],
        "UserReview": [
            "created_at",
            "chat_title",
            "user_id",
            "sender_name",
            "sender_username",
            "is_reply",
            "response_type",
            "response_type_reason",
            "quality_score",
            "quality_reason",
            "edited_at",
            "edit_count",
            "last_seen_at",
            "text",
        ],
        "Chats": ["chat_id", "title", "username", "message_count", "latest_message_at"],
        "Users": ["user_id", "display_name", "username", "message_count", "latest_message_at"],
    }
    return headers_by_title[title]


def _style_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)

    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for column_cells in sheet.columns:
        column_letter = get_column_letter(column_cells[0].column)
        header = str(column_cells[0].value or "")
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        if header == "text":
            width = 60
        elif "reason" in header:
            width = 36
        else:
            width = min(max(max_length + 2, 12), 30)
        sheet.column_dimensions[column_letter].width = width


if __name__ == "__main__":
    main()
