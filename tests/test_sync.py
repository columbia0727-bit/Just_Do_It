from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import config, records, report_service, sync  # noqa: E402
from justdoit.report_service import ReportServiceError  # noqa: E402

NOW = datetime(2026, 10, 14, 12, 0)


def server_log(datetime_str, task, minutes):
    log = report_service.make_log(datetime_str, task, minutes)
    return {**log, "id": report_service.log_id(log)}


def log_id(datetime_str, task, minutes):
    return report_service.log_id(report_service.make_log(datetime_str, task, minutes))


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.tmp.name) / "log" / "work_log.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def write_local(self, *rows):
        for datetime_str, task, minutes in rows:
            records.append_record_to_csv(self.csv_path, datetime_str, task, minutes)

    def local_rows(self):
        return [tuple(row) for row in records.read_rows(self.csv_path)]

    def merge(self, logs=(), deleted=(), retention_days=400):
        state = sync.ServerState(list(logs), set(deleted), (0, 9), retention_days)
        return sync.merge(self.csv_path, state, now=NOW)

    def test_adds_records_from_other_pcs_in_order(self):
        self.write_local(("2026-10-12 09:00:00", "制作", 25))
        result = self.merge(
            logs=[
                server_log("2026-10-12 09:00:00", "制作", 25),  # 手元にもある
                server_log("2026-10-13 20:00:00", "読書", 20),
                server_log("2026-10-11 08:00:00", "学習", 30),
            ]
        )
        self.assertEqual((result.added, result.removed, result.pushed), (2, 0, []))
        self.assertEqual(
            self.local_rows(),
            [
                ("2026-10-12 09:00:00", "制作", "25分"),
                ("2026-10-11 08:00:00", "学習", "30分"),
                ("2026-10-13 20:00:00", "読書", "20分"),
            ],
        )

    def test_removes_records_deleted_on_other_pcs(self):
        self.write_local(("2026-10-12 09:00:00", "制作", 25), ("2026-10-13 09:00:00", "読書", 20))
        result = self.merge(
            logs=[server_log("2026-10-13 09:00:00", "読書", 20)],
            deleted=[log_id("2026-10-12 09:00:00", "制作", 25)],
        )
        self.assertEqual((result.added, result.removed, result.pushed), (0, 1, []))
        self.assertEqual(self.local_rows(), [("2026-10-13 09:00:00", "読書", "20分")])

    def test_edit_on_other_pc_replaces_local_record(self):
        # ほかの PC で「制作 25分」を「ポートフォリオ制作 30分」に直した
        self.write_local(("2026-10-12 09:00:00", "制作", 25))
        result = self.merge(
            logs=[server_log("2026-10-12 09:00:00", "ポートフォリオ制作", 30)],
            deleted=[log_id("2026-10-12 09:00:00", "制作", 25)],
        )
        self.assertEqual((result.added, result.removed), (1, 1))
        self.assertEqual(self.local_rows(), [("2026-10-12 09:00:00", "ポートフォリオ制作", "30分")])

    def test_pushes_local_only_records_within_retention(self):
        self.write_local(
            ("2025-01-01 09:00:00", "とても古い記録", 25),  # 預かる期間より前なので送らない
            ("2026-10-01 09:00:00", "登録前の記録", 25),
        )
        result = self.merge()
        self.assertEqual(result.pushed, [report_service.make_log("2026-10-01 09:00:00", "登録前の記録", 25)])
        self.assertFalse(result.changed)
        self.assertEqual(len(self.local_rows()), 2)

    def test_record_added_again_after_delete_is_kept(self):
        # 消したあとに同じ内容を付け直した場合は、サーバーにある記録を正とする
        self.write_local(("2026-10-12 09:00:00", "制作", 25))
        result = self.merge(
            logs=[server_log("2026-10-12 09:00:00", "制作", 25)],
            deleted=[log_id("2026-10-12 09:00:00", "制作", 25)],
        )
        self.assertEqual((result.added, result.removed), (0, 0))
        self.assertEqual(len(self.local_rows()), 1)

    def test_keeps_unreadable_rows_and_does_not_rewrite_when_nothing_changed(self):
        self.csv_path.parent.mkdir(parents=True)
        self.csv_path.write_text("日時,作業内容,実施時間\n2026-10-12 09:00:00,制作,25分\n", encoding="utf-8-sig")
        before = self.csv_path.stat().st_mtime_ns
        self.merge(logs=[server_log("2026-10-12 09:00:00", "制作", 25)])
        self.assertEqual(self.csv_path.stat().st_mtime_ns, before)

        self.merge(logs=[server_log("2026-10-13 09:00:00", "読書", 20)])
        self.assertEqual(self.local_rows()[0], ("日時", "作業内容", "実施時間"))


class FetchAndApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        config.save_config({"report_email": "me@example.com", "report_token": "tok"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_fetch_sends_queue_first_then_pulls(self):
        pending = [report_service.make_log("2026-10-12 09:00:00", "制作", 25)]
        report_service.enqueue_logs(config.get_report_queue_path(), pending)
        pulled = {
            "status": "success",
            "logs": [server_log("2026-10-13 09:00:00", "読書", 20)],
            "deleted": ["x" * 32],
            "weekday": 6,
            "hour": 21,
            "retention_days": 400,
        }
        with mock.patch.object(report_service, "post_json", side_effect=[{"status": "success"}, pulled]) as post:
            state = sync.fetch_server_state()
        actions = [call.args[1]["action"] for call in post.call_args_list]
        self.assertEqual(actions, ["log", "sync_pull"])  # 送信待ちを先に送る
        self.assertEqual((len(state.logs), state.deleted, state.schedule), (1, {"x" * 32}, (6, 21)))

    def test_fetch_fails_when_queue_cannot_be_sent(self):
        # 「消した」が届かないまま突き合わせると、消した記録が戻ってきてしまうため、同期しない
        pending = [report_service.make_log("2026-10-12 09:00:00", "制作", 25)]
        report_service.enqueue_logs(config.get_report_queue_path(), pending)
        with mock.patch.object(report_service, "post_json", side_effect=OSError("offline")):
            with self.assertRaises(ReportServiceError):
                sync.fetch_server_state()

    def test_apply_saves_schedule_and_queues_local_only_records(self):
        records.append_record_to_csv(config.get_csv_path(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "制作", 25)
        state = sync.ServerState([], set(), (4, 18), 400)
        with mock.patch.object(report_service, "start_sync"):
            result = sync.apply(state)
        self.assertEqual(len(result.pushed), 1)
        self.assertEqual(len(report_service.load_queue(config.get_report_queue_path())), 1)
        self.assertEqual(report_service.get_schedule(config.load_config()), (4, 18))
        # 届くタイミングを合わせたことも結果に残す（設定画面で「変更なし」と表示しないように）
        self.assertEqual(result.schedule_updated, (4, 18))

        with mock.patch.object(report_service, "start_sync"):
            again = sync.apply(state)
        self.assertIsNone(again.schedule_updated)  # すでに同じなら、更新なし


if __name__ == "__main__":
    unittest.main()
