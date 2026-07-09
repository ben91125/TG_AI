from __future__ import annotations

import logging
from datetime import timezone

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

from .analyzers import analyze_message
from .config import Settings
from .storage import SQLiteStore, StoredMessage

LOGGER = logging.getLogger(__name__)


def build_client(settings: Settings) -> TelegramClient:
    return TelegramClient(settings.session_name, settings.api_id, settings.api_hash)


async def register_handlers(client: TelegramClient, settings: Settings, store: SQLiteStore) -> None:
    @client.on(events.NewMessage())
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        sender = await event.get_sender()

        if not _is_group_chat(chat):
            return

        text = event.raw_text or ""
        if not text.strip():
            return

        is_reply = event.message.is_reply
        analysis = analyze_message(text=text, is_reply=is_reply)

        stored = StoredMessage(
            chat_id=event.chat_id or 0,
            chat_title=getattr(chat, "title", None),
            chat_username=getattr(chat, "username", None),
            sender_id=getattr(sender, "id", None),
            sender_username=getattr(sender, "username", None),
            sender_display_name=_display_name(sender),
            message_id=event.message.id,
            text=text,
            reply_to_message_id=event.message.reply_to_msg_id,
            created_at=event.message.date.astimezone(timezone.utc).isoformat(),
            is_game_list_related=analysis.is_game_list_related,
            game_list_reason=analysis.game_list_reason,
            quality_score=analysis.quality_score,
            quality_reason=analysis.quality_reason,
        )
        store.upsert_message(stored)

        LOGGER.info(
            "Stored message chat_id=%s message_id=%s sender_id=%s reply=%s game_list=%s quality=%s",
            stored.chat_id,
            stored.message_id,
            stored.sender_id,
            bool(stored.reply_to_message_id),
            stored.is_game_list_related,
            stored.quality_score,
        )

        if stored.sender_id in settings.tracked_user_ids and stored.reply_to_message_id:
            LOGGER.info(
                "Tracked user reply user_id=%s quality=%s reason=%s",
                stored.sender_id,
                stored.quality_score,
                stored.quality_reason,
            )


def _is_group_chat(chat: object) -> bool:
    return isinstance(chat, (Chat, Channel))



def _display_name(sender: object) -> str | None:
    if not isinstance(sender, User):
        return None
    parts = [sender.first_name or "", sender.last_name or ""]
    display_name = " ".join(part for part in parts if part).strip()
    return display_name or sender.username or None
