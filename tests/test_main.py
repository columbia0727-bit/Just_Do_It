from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


class ParseMinutesTest(unittest.TestCase):
    def test_parses_suffixed_and_plain_values(self):
        self.assertEqual(main.parse_minutes("25分"), 25)
        self.assertEqual(main.parse_minutes("100"), 100)
        self.assertEqual(main.parse_minutes(5), 5)

    def test_returns_zero_for_invalid_values(self):
        self.assertEqual(main.parse_minutes("abc"), 0)
        self.assertEqual(main.parse_minutes(""), 0)


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "log" / "work_log.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_then_load_round_trip(self):
        main.append_record_to_csv(self.csv_path, "2026-08-18 09:00:00", "制作", 25)
        main.append_record_to_csv(self.csv_path, "2026-08-18 10:00:00", "制作", 5)
        main.append_record_to_csv(self.csv_path, "2026-08-19 10:00:00", "学習", 30)

        records = main.load_records(self.csv_path)
        self.assertEqual(len(records), 3)
        self.assertEqual(main.summarize_by_task(records).to_dict(), {"学習": 30, "制作": 30})

    def test_summarize_by_day_fills_missing_days(self):
        main.append_record_to_csv(self.csv_path, "2026-08-18 09:00:00", "制作", 25)
        main.append_record_to_csv(self.csv_path, "2026-08-20 09:00:00", "制作", 10)

        by_day = main.summarize_by_day(
            main.load_records(self.csv_path), days=3, today=datetime(2026, 8, 20)
        )
        self.assertEqual(list(by_day.values), [25, 0, 10])

    def test_rows_with_invalid_datetime_are_skipped(self):
        self.csv_path.parent.mkdir(parents=True)
        self.csv_path.write_text(
            "日時,作業内容,実施時間\n2026-08-18 09:00:00,制作,25分\n", encoding="utf-8-sig"
        )
        self.assertEqual(len(main.load_records(self.csv_path)), 1)


class GasUrlTest(unittest.TestCase):
    def test_only_apps_script_urls_are_valid(self):
        self.assertTrue(main.is_valid_gas_url("https://script.google.com/macros/s/xxx/exec"))
        self.assertFalse(main.is_valid_gas_url("https://example.com/"))


if __name__ == "__main__":
    unittest.main()
