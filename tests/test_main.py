from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

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


class FormatHoursMinsTest(unittest.TestCase):
    def test_omits_zero_hours_and_zero_minutes(self):
        self.assertEqual(main.format_hours_mins(41), "41分")
        self.assertEqual(main.format_hours_mins(0), "0分")
        self.assertEqual(main.format_hours_mins(120), "2時間")
        self.assertEqual(main.format_hours_mins(80), "1時間 20分")


class ReportServiceTest(unittest.TestCase):
    URL = "https://script.google.com/macros/s/test/exec"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        patcher = mock.patch.object(main, "get_data_dir", return_value=data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.queue_path = main.get_report_queue_path()
        main.save_config({"report_email": "me@example.com", "report_token": "tok"})

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, task):
        return {"datetime": "2026-10-12 09:00:00", "task": task, "minutes": 25}

    def test_call_report_service_raises_with_server_code(self):
        with mock.patch.object(
            main, "post_json", return_value={"status": "error", "code": "unauthorized", "message": "NG"}
        ):
            with self.assertRaises(main.ReportServiceError) as ctx:
                main.call_report_service(self.URL, {})
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_call_report_service_marks_network_errors(self):
        with mock.patch.object(main, "post_json", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(main.ReportServiceError) as ctx:
                main.call_report_service(self.URL, {})
        self.assertEqual(ctx.exception.code, "network")

    def test_sync_sends_all_logs_with_token(self):
        main.enqueue_report_logs(self.queue_path, [self.log("制作"), self.log("学習")])
        with mock.patch.object(main, "post_json", return_value={"status": "success"}) as post:
            main.sync_report_queue(self.URL, self.queue_path)

        sent = [call.args[1] for call in post.call_args_list]
        self.assertEqual([p["task"] for p in sent], ["制作", "学習"])
        self.assertTrue(all(p["action"] == "log" and p["token"] == "tok" for p in sent))
        self.assertEqual(main.load_report_queue(self.queue_path), [])

    def test_sync_keeps_unsent_logs_on_network_error(self):
        main.enqueue_report_logs(self.queue_path, [self.log("制作"), self.log("学習")])
        responses = [{"status": "success"}, urllib.error.URLError("offline")]
        with mock.patch.object(main, "post_json", side_effect=responses):
            main.sync_report_queue(self.URL, self.queue_path)

        self.assertEqual(main.load_report_queue(self.queue_path), [self.log("学習")])

    def test_sync_drops_logs_rejected_by_server(self):
        main.enqueue_report_logs(self.queue_path, [self.log("制作")])
        rejected = {"status": "error", "code": "invalid", "message": "NG"}
        with mock.patch.object(main, "post_json", return_value=rejected):
            main.sync_report_queue(self.URL, self.queue_path)

        self.assertEqual(main.load_report_queue(self.queue_path), [])

    def test_sync_clears_registration_when_token_is_revoked(self):
        main.enqueue_report_logs(self.queue_path, [self.log("制作")])
        revoked = {"status": "error", "code": "unauthorized", "message": "NG"}
        with mock.patch.object(main, "post_json", return_value=revoked):
            main.sync_report_queue(self.URL, self.queue_path)

        self.assertNotIn("report_token", main.load_config())
        self.assertEqual(main.load_report_queue(self.queue_path), [])

    def test_backfill_includes_only_recent_records(self):
        csv_path = main.get_csv_path()
        main.append_record_to_csv(csv_path, "2026-09-01 09:00:00", "古い", 25)
        main.append_record_to_csv(csv_path, "2026-10-10 09:00:00", "制作", 25)

        logs = main.build_backfill_logs(
            main.load_records(csv_path), days=14, now=datetime(2026, 10, 13)
        )
        self.assertEqual(
            logs, [{"datetime": "2026-10-10 09:00:00", "task": "制作", "minutes": 25}]
        )


if __name__ == "__main__":
    unittest.main()
