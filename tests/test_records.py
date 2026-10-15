from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import records, report_service  # noqa: E402


class ParseMinutesTest(unittest.TestCase):
    def test_parses_suffixed_and_plain_values(self):
        self.assertEqual(records.parse_minutes("25分"), 25)
        self.assertEqual(records.parse_minutes("100"), 100)
        self.assertEqual(records.parse_minutes(5), 5)

    def test_returns_zero_for_invalid_values(self):
        self.assertEqual(records.parse_minutes("abc"), 0)
        self.assertEqual(records.parse_minutes(""), 0)


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "log" / "work_log.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def append(self, datetime_str, task, minutes):
        records.append_record_to_csv(self.csv_path, datetime_str, task, minutes)

    def test_append_then_load_round_trip(self):
        self.append("2026-08-18 09:00:00", "制作", 25)
        self.append("2026-08-18 10:00:00", "制作", 5)
        self.append("2026-08-19 10:00:00", "学習", 30)

        loaded = records.load_records(self.csv_path)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(records.summarize_by_task(loaded).to_dict(), {"学習": 30, "制作": 30})

    def test_summarize_by_day_fills_missing_days(self):
        self.append("2026-08-18 09:00:00", "制作", 25)
        self.append("2026-08-20 09:00:00", "制作", 10)

        by_day = records.summarize_by_day(
            records.load_records(self.csv_path), days=3, today=datetime(2026, 8, 20)
        )
        self.assertEqual(list(by_day.values), [25, 0, 10])

    def test_summarize_period_week_and_month(self):
        self.append("2026-08-01 09:00:00", "古い", 30)
        self.append("2026-08-14 09:00:00", "学習", 20)
        self.append("2026-08-20 09:00:00", "制作", 25)
        self.append("2026-08-20 10:00:00", "制作", 5)
        loaded = records.load_records(self.csv_path)
        today = datetime(2026, 8, 20)

        week = records.summarize_period(loaded, "week", today=today)
        self.assertEqual(week.labels[0], "8/14")
        self.assertEqual(week.values, [20, 0, 0, 0, 0, 0, 30])
        self.assertEqual((week.total_minutes, week.active_days, week.span_days), (50, 2, 7))
        self.assertEqual(week.by_task.to_dict(), {"制作": 30, "学習": 20})

        month = records.summarize_period(loaded, "month", today=today)
        self.assertEqual((month.total_minutes, month.span_days), (80, 30))

    def test_summarize_period_year_is_monthly_in_hours(self):
        self.append("2025-08-31 09:00:00", "範囲外", 600)
        self.append("2025-09-01 09:00:00", "制作", 90)
        self.append("2026-08-20 09:00:00", "制作", 30)

        year = records.summarize_period(records.load_records(self.csv_path), "year", today=datetime(2026, 8, 20))
        self.assertEqual(year.labels[0], "9月")
        self.assertEqual(year.labels[-1], "8月")
        self.assertEqual(year.values[0], 1.5)
        self.assertEqual(year.values[-1], 0.5)
        self.assertEqual((year.unit, year.total_minutes), ("時間", 120))

    def test_summarize_earlier_periods(self):
        self.append("2026-08-10 09:00:00", "学習", 20)
        self.append("2026-08-12 09:00:00", "制作", 30)
        self.append("2026-08-20 09:00:00", "制作", 25)
        loaded = records.load_records(self.csv_path)
        today = datetime(2026, 8, 20)

        week = records.summarize_period(loaded, "week", today=today, offset=1)
        self.assertEqual((week.title, week.labels[0], week.labels[-1]), ("8/7〜8/13", "8/7", "8/13"))
        self.assertEqual(week.total_minutes, 50)

        month = records.summarize_period(loaded, "month", today=today, offset=1)
        self.assertEqual((month.start.isoformat(), month.end.isoformat()), ("2026-06-22", "2026-07-21"))

        previous_year = records.summarize_period(loaded, "year", today=today, offset=1)
        self.assertEqual(previous_year.title, "2024年9月〜2025年8月")
        self.assertEqual((previous_year.labels[0], previous_year.labels[-1]), ("9月", "8月"))
        self.assertEqual(records.summarize_period(loaded, "week", today=today).title, "直近7日")

    def test_rows_with_invalid_datetime_are_skipped(self):
        self.csv_path.parent.mkdir(parents=True)
        self.csv_path.write_text(
            "日時,作業内容,実施時間\n2026-08-18 09:00:00,制作,25分\n", encoding="utf-8-sig"
        )
        self.assertEqual(len(records.load_records(self.csv_path)), 1)


class LoadEmptyCsvTest(unittest.TestCase):
    def test_missing_or_empty_csv_has_no_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "work_log.csv"
            self.assertTrue(records.load_records(csv_path).empty)
            csv_path.write_bytes(b"")
            self.assertTrue(records.load_records(csv_path).empty)
            csv_path.write_bytes("﻿".encode())
            self.assertTrue(records.load_records(csv_path).empty)


class EditRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "work_log.csv"
        records.append_record_to_csv(self.csv_path, "2026-10-12 09:00:00", "制作", 25)
        records.append_record_to_csv(self.csv_path, "壊れた行", "x", 1)
        records.append_record_to_csv(self.csv_path, "2026-10-13 09:00:00", "学習", 30)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_records_is_newest_first_and_skips_broken_rows(self):
        listed = records.list_records(self.csv_path)
        self.assertEqual([(r.row_index, r.task, r.minutes) for r in listed], [(2, "学習", 30), (0, "制作", 25)])

    def test_update_and_delete_keep_other_rows(self):
        records.update_record(self.csv_path, 2, "読書", 45)
        records.delete_record(self.csv_path, 0)

        lines = self.csv_path.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(lines, ["壊れた行,x,1分", "2026-10-13 09:00:00,読書,45分"])

    def test_group_by_month_is_newest_first(self):
        records.append_record_to_csv(self.csv_path, "2026-09-30 23:00:00", "読書", 20)
        months = records.group_by_month(records.list_records(self.csv_path))
        self.assertEqual([key for key, _ in months], [(2026, 10), (2026, 9)])
        self.assertEqual([r.task for r in months[0][1]], ["学習", "制作"])
        self.assertEqual([r.task for r in months[1][1]], ["読書"])

    def test_update_can_change_datetime(self):
        records.update_record(self.csv_path, 0, "制作", 25, recorded_at=datetime(2026, 10, 11, 21, 30))
        self.assertEqual(self.csv_path.read_text(encoding="utf-8-sig").splitlines()[0], "2026-10-11 21:30:00,制作,25分")

    def test_validate_when(self):
        now = datetime(2026, 10, 14, 12, 0)
        self.assertEqual(records.validate_when("2026/10/13", "9:05", now), datetime(2026, 10, 13, 9, 5))
        # 「-」区切りの日付と、全角の「：」も受け付ける
        self.assertEqual(records.validate_when("2026-10-14", "12：00", now), datetime(2026, 10, 14, 12, 0))
        self.assertIn("日付", records.validate_when("10/13", "9:05", now))
        self.assertIn("時刻", records.validate_when("2026/10/13", "25:00", now))
        self.assertIn("これから先", records.validate_when("2026/10/14", "12:01", now))

    def test_recorded_at_on_uses_the_time_of_recording(self):
        now = datetime(2026, 10, 15, 10, 44, 27, 123456)
        self.assertEqual(records.recorded_at_on(date(2026, 10, 13), now), datetime(2026, 10, 13, 10, 44, 27))
        self.assertEqual(records.recorded_at_on(date(2026, 10, 15), now), datetime(2026, 10, 15, 10, 44, 27))
        # 同じ日に同じ作業・同じ時間を続けて記録しても、時刻が違うので別の記録（別の ID）になる
        later = records.recorded_at_on(date(2026, 10, 13), now + timedelta(seconds=30))
        log = report_service.make_log
        first = log(records.recorded_at_on(date(2026, 10, 13), now).strftime(records.DATETIME_FORMAT), "読書", 20)
        second = log(later.strftime(records.DATETIME_FORMAT), "読書", 20)
        self.assertNotEqual(report_service.log_id(first), report_service.log_id(second))

    def test_day_label(self):
        today = date(2026, 10, 14)
        labels = [records.day_label(today - timedelta(days=d), today) for d in range(3)]
        self.assertEqual(labels, ["今日 10/14（水）", "昨日 10/13（火）", "10/12（月）"])

    def test_month_weeks_start_on_monday(self):
        weeks = records.month_weeks(2026, 10)
        # 2026年10月1日は木曜。月曜はじまりなので、1週目は月〜水が空く
        self.assertEqual(weeks[0], [None, None, None, date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
                                    date(2026, 10, 4)])
        self.assertEqual(weeks[-1][:6], [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28),
                                         date(2026, 10, 29), date(2026, 10, 30), date(2026, 10, 31)])
        self.assertIsNone(weeks[-1][6])
        self.assertEqual(sum(day is not None for week in weeks for day in week), 31)

    def test_validate_record(self):
        self.assertEqual(records.validate_record(" 制作 ", "25"), ("制作", 25))
        self.assertEqual(records.validate_record("", "25"), "やったことを入力してください")
        self.assertIn("1〜1440", records.validate_record("制作", "0"))
        self.assertIn("1〜1440", records.validate_record("制作", "abc"))


class DailySummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "work_log.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, rows):
        for datetime_str, task, minutes in rows:
            records.append_record_to_csv(self.csv_path, datetime_str, task, minutes)
        return records.load_records(self.csv_path)

    def test_recent_tasks_are_unique_and_newest_first(self):
        loaded = self.load(
            [
                ("2026-10-10 09:00:00", "制作", 25),
                ("2026-10-11 09:00:00", "学習", 5),
                ("2026-10-12 09:00:00", "制作", 5),
            ]
        )
        self.assertEqual(records.recent_tasks(loaded), ["制作", "学習"])
        self.assertEqual(records.recent_tasks(loaded, limit=1), ["制作"])

    def test_today_minutes_and_streak(self):
        loaded = self.load(
            [
                ("2026-10-09 09:00:00", "制作", 25),  # 1日空いているので連続には数えない
                ("2026-10-11 09:00:00", "制作", 25),
                ("2026-10-12 09:00:00", "制作", 25),
                ("2026-10-13 09:00:00", "学習", 10),
                ("2026-10-13 20:00:00", "学習", 15),
            ]
        )
        self.assertEqual(records.today_minutes(loaded, today=datetime(2026, 10, 13, 21)), 25)
        self.assertEqual(records.streak_days(loaded, today=datetime(2026, 10, 13, 21)), 3)
        # 今日まだ記録していなくても、昨日まで続いていれば途切れない
        self.assertEqual(records.streak_days(loaded, today=datetime(2026, 10, 14, 8)), 3)
        self.assertEqual(records.streak_days(loaded, today=datetime(2026, 10, 15, 8)), 0)


class FormatHoursMinsTest(unittest.TestCase):
    def test_omits_zero_hours_and_zero_minutes(self):
        self.assertEqual(records.format_hours_mins(41), "41分")
        self.assertEqual(records.format_hours_mins(0), "0分")
        self.assertEqual(records.format_hours_mins(120), "2時間")
        self.assertEqual(records.format_hours_mins(80), "1時間 20分")


if __name__ == "__main__":
    unittest.main()
