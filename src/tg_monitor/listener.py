from __future__ import annotations

import logging
from datetime import timezone

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User

from .game_list.classifier import analyze_game_list_message
from .user_review.classifier import analyze_user_reply
from .config import Settings
from .storage import GameListAnalysis, RawMessage, SQLiteStore, UserReplyAnalysis

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
        game_list_result = analyze_game_list_message(text=text)
        user_reply_result = analyze_user_reply(text=text, is_reply=is_reply)

        raw_message = RawMessage(
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
        )
        store.upsert_raw_message(raw_message)
        store.upsert_game_list_analysis(
            GameListAnalysis(
                chat_id=raw_message.chat_id,
                message_id=raw_message.message_id,
                is_related=game_list_result.is_related,
                reason=game_list_result.reason,
            )
        )
        store.upsert_user_reply_analysis(
            UserReplyAnalysis(
                chat_id=raw_message.chat_id,
                message_id=raw_message.message_id,
                user_id=raw_message.sender_id,
                is_reply=is_reply,
                response_type=user_reply_result.response_type,
                response_type_reason=user_reply_result.response_type_reason,
                quality_score=user_reply_result.quality_score,
                quality_reason=user_reply_result.quality_reason,
            )
        )

        LOGGER.info(
            "Stored raw message chat_id=%s message_id=%s sender_id=%s reply=%s",
            raw_message.chat_id,
            raw_message.message_id,
            raw_message.sender_id,
            bool(raw_message.reply_to_message_id),
        )
        LOGGER.info(
            "Game-list analysis chat_id=%s message_id=%s related=%s reason=%s",
            raw_message.chat_id,
            raw_message.message_id,
            game_list_result.is_related,
            game_list_result.reason,
        )

        if raw_message.sender_id in settings.tracked_user_ids and raw_message.reply_to_message_id:
            LOGGER.info(
                "Tracked user reply user_id=%s type=%s quality=%s reason=%s",
                raw_message.sender_id,
                user_reply_result.response_type,
                user_reply_result.quality_score,
                user_reply_result.quality_reason,
            )


def _is_group_chat(chat: object) -> bool:
    return isinstance(chat, (Chat, Channel))



def _display_name(sender: object) -> str | None:
    if not isinstance(sender, User):
        return None
    parts = [sender.first_name or "", sender.last_name or ""]
    display_name = " ".join(part for part in parts if part).strip()
    return display_name or sender.username or None
