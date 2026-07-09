from __future__ import annotations

from .config import load_settings
from .storage import SQLiteStore


def main() -> None:
    settings = load_settings()
    store = SQLiteStore(settings.sqlite_path)
    try:
        rows = store.tracked_user_summary(settings.tracked_user_ids)
        if not rows:
            print("No tracked-user reply data yet.")
            return

        for row in rows:
            print(
                "user_id={user_id} replies={reply_count} avg_quality={avg_quality_score} "
                "high_quality={high_quality_replies} game_list_related={game_list_related_replies}".format(
                    **row
                )
            )
    finally:
        store.close()


if __name__ == "__main__":
    main()
