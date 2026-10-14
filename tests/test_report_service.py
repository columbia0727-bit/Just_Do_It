from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import config, records, report_service  # noqa: E402
from justdoit.report_service import ReportServiceError  # noqa: E402


class ReportServiceTest(unittest.TestCase):
    URL = "https://script.google.com/macros/s/test/exec"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.queue_path = config.get_report_queue_path()
        config.save_config({"report_email": "me@example.com", "report_token": "tok"})

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, task):
        return report_service.make_log("2026-10-12 09:00:00", task, 25)

    def mock_post(self, **kwargs):
        return mock.patch.object(report_service, "post_json", **kwargs)

    def test_call_service_raises_with_server_code(self):
        with self.mock_post(return_value={"status": "error", "code": "unauthorized", "message": "NG"}):
            with self.assertRaises(ReportServiceError) as ctx:
                report_service.call_service(self.URL, {})
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_call_service_marks_network_errors(self):
        with self.mock_post(side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(ReportServiceError) as ctx:
                report_service.call_service(self.URL, {})
        self.assertEqual(ctx.exception.code, "network")

    def test_sync_sends_all_logs_with_token(self):
        report_service.enqueue_logs(self.queue_path, [self.log("制作"), self.log("学習")])
        with self.mock_post(return_value={"status": "success"}) as post:
            report_service.sync_queue(self.URL, self.queue_path)

        sent = [call.args[1] for call in post.call_args_list]
        self.assertEqual([p["task"] for p in sent], ["制作", "学習"])
        self.assertTrue(all(p["action"] == "log" and p["token"] == "tok" for p in sent))
        self.assertEqual(report_service.load_queue(self.queue_path), [])

    def test_sync_sends_same_id_when_resending_same_log(self):
        # サーバーが重複をはじけるよう、同じ記録には毎回同じ ID を付ける
        with self.mock_post(return_value={"status": "success"}) as post:
            for task in ["制作", "制作", "学習"]:
                report_service.enqueue_logs(self.queue_path, [self.log(task)])
                report_service.sync_queue(self.URL, self.queue_path)

        ids = [call.args[1]["id"] for call in post.call_args_list]
        self.assertRegex(ids[0], r"^[0-9a-f]{32}$")
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])

    def test_sync_sends_updates_and_deletes_in_order(self):
        # 記録一覧で直した・消した記録は、直す前の内容から作った ID でサーバー側の記録を探す
        original = self.log("制作")
        report_service.enqueue_logs(
            self.queue_path,
            [
                original,
                report_service.make_update(original, "ポートフォリオ制作", 30),
                report_service.make_delete(report_service.make_log(original["datetime"], "ポートフォリオ制作", 30)),
            ],
        )
        with self.mock_post(return_value={"status": "success"}) as post:
            report_service.sync_queue(self.URL, self.queue_path)

        added, updated, deleted = [call.args[1] for call in post.call_args_list]
        self.assertEqual([p["action"] for p in (added, updated, deleted)], ["log", "update_log", "delete_log"])
        # 修正は「直す前の ID」で探し、「直した後の ID」に書き換える。削除は直した後の ID で探す
        self.assertEqual(updated["id"], added["id"])
        self.assertEqual((updated["new_task"], updated["new_minutes"]), ("ポートフォリオ制作", 30))
        self.assertNotEqual(updated["new_id"], added["id"])
        self.assertEqual(deleted["id"], updated["new_id"])
        self.assertTrue(all(p["token"] == "tok" for p in (added, updated, deleted)))
        self.assertEqual(report_service.load_queue(self.queue_path), [])

    def test_old_queue_items_without_action_are_sent_as_logs(self):
        # 以前のバージョンで積んだ記録（action なし）も、そのまま送れる
        report_service.enqueue_logs(self.queue_path, [self.log("制作")])
        with self.mock_post(return_value={"status": "success"}) as post:
            report_service.sync_queue(self.URL, self.queue_path)
        self.assertEqual(post.call_args.args[1]["action"], "log")

    def test_sync_keeps_unsent_logs_on_network_error(self):
        report_service.enqueue_logs(self.queue_path, [self.log("制作"), self.log("学習")])
        with self.mock_post(side_effect=[{"status": "success"}, urllib.error.URLError("offline")]):
            report_service.sync_queue(self.URL, self.queue_path)

        self.assertEqual(report_service.load_queue(self.queue_path), [self.log("学習")])

    def test_sync_drops_logs_rejected_by_server(self):
        report_service.enqueue_logs(self.queue_path, [self.log("制作")])
        with self.mock_post(return_value={"status": "error", "code": "invalid", "message": "NG"}):
            report_service.sync_queue(self.URL, self.queue_path)

        self.assertEqual(report_service.load_queue(self.queue_path), [])

    def test_sync_clears_registration_when_token_is_revoked(self):
        report_service.enqueue_logs(self.queue_path, [self.log("制作")])
        with self.mock_post(return_value={"status": "error", "code": "unauthorized", "message": "NG"}):
            report_service.sync_queue(self.URL, self.queue_path)

        self.assertNotIn("report_token", config.load_config())
        self.assertEqual(report_service.load_queue(self.queue_path), [])

    def test_backfill_includes_only_recent_records(self):
        csv_path = config.get_csv_path()
        records.append_record_to_csv(csv_path, "2026-09-01 09:00:00", "古い", 25)
        records.append_record_to_csv(csv_path, "2026-10-10 09:00:00", "制作", 25)

        logs = report_service.build_backfill_logs(
            records.load_records(csv_path), days=14, now=datetime(2026, 10, 13)
        )
        self.assertEqual(logs, [report_service.make_log("2026-10-10 09:00:00", "制作", 25)])


class ScheduleTest(unittest.TestCase):
    def test_saved_schedule_is_returned(self):
        settings = {}
        report_service.save_schedule(settings, 6, 21)
        self.assertEqual(report_service.get_schedule(settings), (6, 21))

    def test_missing_or_invalid_schedule_falls_back_to_default(self):
        # 時刻を選べるようになる前に登録した人は、月曜 9時のまま
        self.assertEqual(report_service.get_schedule({}), (0, 9))
        self.assertEqual(report_service.get_schedule({"report_weekday": 7, "report_hour": 9}), (0, 9))
        self.assertEqual(report_service.get_schedule({"report_weekday": 1, "report_hour": 3}), (0, 9))

    def test_format_schedule(self):
        self.assertEqual(report_service.format_schedule(0, 9), "毎週月曜 9時ごろ")
        self.assertEqual(report_service.format_schedule(6, 21), "毎週日曜 21時ごろ")


if __name__ == "__main__":
    unittest.main()
