import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from datetime import date, datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("export.py")
SPEC = importlib.util.spec_from_file_location("tg_history_export", MODULE_PATH)
export = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = export
SPEC.loader.exec_module(export)


class ExportHelpersTest(unittest.TestCase):
    def test_discovers_multiple_accounts_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["zeta.env", "alpha.env", "example.env", "bad name.env"]:
                (root / name).touch()
            self.assertEqual(export.discover_accounts(root), ["alpha", "zeta"])

    def test_account_menu_returns_selected_account(self):
        with patch.object(export, "discover_accounts", return_value=["alpha", "zeta"]):
            with patch("builtins.input", side_effect=["2"]):
                self.assertEqual(export.prompt_account(), "zeta")

    def test_full_export_uses_month_file(self):
        value = export.build_range(None, None)
        self.assertEqual(
            export.log_path(Path("logs"), 6450183261, value, date(2026, 8, 7)),
            Path("logs/6450183261_2026-08.jsonl"),
        )

    def test_range_export_uses_one_file_across_months(self):
        value = export.build_range(date(2026, 7, 20), date(2026, 8, 7))
        july = export.log_path(Path("logs"), 6450183261, value, date(2026, 7, 21))
        august = export.log_path(Path("logs"), 6450183261, value, date(2026, 8, 6))
        expected = Path("logs/6450183261_range_2026-07-20_2026-08-07.jsonl")
        self.assertEqual(july, expected)
        self.assertEqual(august, expected)

    def test_range_boundaries_are_inclusive_in_taipei(self):
        value = export.build_range(date(2026, 8, 1), date(2026, 8, 7))
        self.assertTrue(value.contains(datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)))
        self.assertTrue(
            value.contains(datetime(2026, 8, 7, 15, 59, 59, 999999, tzinfo=timezone.utc))
        )
        self.assertFalse(value.contains(datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)))

    def test_completed_month_uses_full_calendar_month(self):
        start, end = export.completed_month_dates(
            date(2024, 2, 1), today=date(2024, 3, 1)
        )
        self.assertEqual(start, date(2024, 2, 1))
        self.assertEqual(end, date(2024, 2, 29))

    def test_current_month_cannot_be_archived(self):
        with self.assertRaises(SystemExit):
            export.completed_month_dates(date(2026, 8, 1), today=date(2026, 8, 18))

    def test_month_archive_uses_formal_month_filename(self):
        value = export.build_range(date(2026, 7, 1), date(2026, 7, 31))
        path = export.log_path(
            Path("logs"),
            6450183261,
            value,
            date(2026, 7, 5),
            archive_month=date(2026, 7, 1),
        )
        self.assertEqual(path, Path("logs/6450183261_2026-07.jsonl"))

    def test_existing_ids_ignores_bad_and_non_message_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.jsonl"
            path.write_text(
                '\n'.join(
                    [
                        json.dumps({"event_type": "message", "msg_id": 10}),
                        json.dumps({"event_type": "reaction", "msg_id": 10}),
                        "not-json",
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(export.read_existing_ids(path), {10})

    def test_month_merge_preserves_old_only_and_refreshes_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "123_2026-07.jsonl"
            fresh = root / "123_2026-07.jsonl.refresh.part"
            old_rows = [
                {"time": "2026-07-01T00:00:00+08:00", "msg_id": 1, "event_type": "message", "text": "old"},
                {"time": "2026-07-02T00:00:00+08:00", "msg_id": 2, "event_type": "message", "text": "deleted later"},
            ]
            fresh_rows = [
                {"time": "2026-07-01T00:00:00+08:00", "msg_id": 1, "event_type": "message", "text": "edited"},
                {"time": "2026-07-03T00:00:00+08:00", "msg_id": 3, "event_type": "message", "text": "new"},
            ]
            for row in old_rows:
                export.append_jsonl(existing, row)
            for row in fresh_rows:
                export.append_jsonl(fresh, row)

            merged_path, old_count, fresh_count, merged_count = export.merge_month_archive(
                existing, fresh
            )
            merged = export.read_jsonl_records(merged_path)
            self.assertEqual((old_count, fresh_count, merged_count), (2, 2, 3))
            self.assertEqual([row["msg_id"] for row in merged], [1, 2, 3])
            self.assertEqual(merged[0]["text"], "edited")
            self.assertEqual(merged[1]["text"], "deleted later")
            self.assertEqual(export.read_jsonl_records(existing), old_rows)


class LoginTest(unittest.IsolatedAsyncioTestCase):
    async def test_blank_phone_uses_telethon_interactive_prompt(self):
        client = type("Client", (), {})()
        client.start = AsyncMock()
        await export.start_user_client(client, None)
        client.start.assert_awaited_once_with()

    async def test_configured_phone_is_passed_to_telethon(self):
        client = type("Client", (), {})()
        client.start = AsyncMock()
        await export.start_user_client(client, "+886900000000")
        client.start.assert_awaited_once_with(phone="+886900000000")


class MediaDownloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_media_failure_is_retried_and_completed(self):
        class FakeFile:
            ext = ".jpg"

        class FakeMessage:
            id = 123
            file = FakeFile()

            def __init__(self):
                self.attempts = 0

            async def download_media(self, file):
                self.attempts += 1
                if self.attempts == 1:
                    raise OSError("temporary failure")
                Path(file).write_bytes(b"image")
                return file

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            metadata = {"type": "photo", "download_status": "pending"}
            message = FakeMessage()
            with patch.object(export.asyncio, "sleep", new=AsyncMock()):
                await export.download_media(
                    message,
                    metadata,
                    root,
                    date(2026, 8, 7),
                    export.asyncio.Semaphore(1),
                    timeout_seconds=5,
                    retries=1,
                )
            self.assertEqual(message.attempts, 2)
            self.assertEqual(metadata["download_status"], "complete")
            self.assertTrue((root / "2026-08" / "123.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
