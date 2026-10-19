from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import __version__, config, records, report_service, support  # noqa: E402

NOW = datetime(2026, 10, 16, 15, 0)


class SupportInfoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in [
            mock.patch.object(config, "get_data_dir", return_value=Path(tmp.name)),
            mock.patch.object(report_service, "is_registered", return_value=False),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_basic_information(self):
        records.append_record_to_csv(config.get_csv_path(), "2026-10-15 09:00:00", "ひみつの作業", 25)
        records.append_record_to_csv(config.get_csv_path(), "2026-10-16 13:41:00", "ひみつの作業", 5)

        text = support.support_info(last_sync=None, now=NOW)
        self.assertIn(f"バージョン: {__version__}", text)
        self.assertIn(config.os_description(), text)
        self.assertIn("作業ログ: 2件（最新 2026-10-16 13:41）", text)
        self.assertIn("週次レポート: 未登録", text)
        self.assertIn("error.log（新しいもの）:\nなし", text)
        # 作業内容は他人に見せたくないことがあるので含めない
        self.assertNotIn("ひみつの作業", text)

    def test_registered_without_email_or_token(self):
        config.save_config({"report_email": "me@example.com"})
        with (
            mock.patch.object(report_service, "is_registered", return_value=True),
            mock.patch.object(config, "get_report_token", return_value="secret-token"),
        ):
            report_service.save_queue(config.get_report_queue_path(), [{"action": "add"}])
            text = support.support_info(last_sync=datetime(2026, 10, 16, 13, 40), now=NOW)

        self.assertIn("週次レポート: 登録済み・送信待ち 1件・最後に同期 10/16 13:40", text)
        self.assertNotIn("me@example.com", text)
        self.assertNotIn("secret-token", text)

    def test_only_recent_errors(self):
        for i in range(5):
            config.append_error_log(f"エラー{i}\n詳しい内容 --- 途中の線")

        errors = support.recent_errors(config.get_error_log_path())
        self.assertNotIn("エラー1", errors)
        self.assertIn("エラー2", errors)
        self.assertIn("エラー4", errors)
        self.assertEqual(errors.count("\n--- "), 2)  # 3件（行の途中の「--- 」では区切らない）


if __name__ == "__main__":
    unittest.main()
