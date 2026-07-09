from __future__ import annotations

import asyncio
import logging

from .config import load_settings
from .listener import build_client, register_handlers
from .storage import SQLiteStore


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


async def async_main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    store = SQLiteStore(settings.sqlite_path)
    client = build_client(settings)

    await register_handlers(client, settings, store)
    await client.start()

    logging.getLogger(__name__).info("Telegram monitor started.")
    logging.getLogger(__name__).info("Tracked user IDs: %s", sorted(settings.tracked_user_ids))
    logging.getLogger(__name__).info("SQLite path: %s", settings.sqlite_path)

    try:
        await client.run_until_disconnected()
    finally:
        rows = store.tracked_user_summary(settings.tracked_user_ids)
        for row in rows:
            logging.getLogger(__name__).info(
                "user_id=%s replies=%s avg_quality=%s high_quality=%s game_list_related=%s",
                row["user_id"],
                row["reply_count"],
                row["avg_quality_score"],
                row["high_quality_replies"],
                row["game_list_related_replies"],
            )
        store.close()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
