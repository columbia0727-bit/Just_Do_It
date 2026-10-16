import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import config  # noqa: E402


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_not_saved(self):
        self.assertEqual(config.load_preferences(), config.Preferences())

    def test_save_and_load_keeps_other_settings(self):
        config.save_config({"report_token": "tok"})
        config.save_preferences(config.Preferences(focus_minutes=50, break_minutes=5, notify_os=False))

        prefs = config.load_preferences()
        self.assertEqual((prefs.focus_minutes, prefs.break_minutes, prefs.notify_os), (50, 5, False))
        self.assertEqual(config.load_config()["report_token"], "tok")

    def test_invalid_values_fall_back_to_defaults(self):
        config.save_config(
            {"preferences": {"focus_minutes": 7, "break_minutes": "10", "notify_sound": "no", "appearance": "blue"}}
        )
        self.assertEqual(config.load_preferences(), config.Preferences())

    def test_appearance_is_saved(self):
        config.save_preferences(config.Preferences(appearance="dark"))
        self.assertEqual(config.load_preferences().appearance, "dark")

    def test_weekly_goal(self):
        self.assertEqual(config.load_preferences().weekly_goal_minutes, 0, "初めは目標なし")
        config.save_preferences(config.Preferences(weekly_goal_minutes=180))
        self.assertEqual(config.load_preferences().weekly_goal_minutes, 180)
        # 選択肢にない値（手で書き換えた・新しいバージョンの値など）は、目標なしにする
        config.save_config({"preferences": {"weekly_goal_minutes": 7}})
        self.assertEqual(config.load_preferences().weekly_goal_minutes, 0)


class FakeVault:
    """資格情報マネージャーの代わり（fail=True なら、どの操作も失敗する）"""

    def __init__(self, fail=False):
        self.saved = {}
        self.fail = fail

    def get_password(self, service, username):
        if self.fail:
            raise RuntimeError("使えない")
        return self.saved.get((service, username))

    def set_password(self, service, username, password):
        if self.fail:
            raise RuntimeError("使えない")
        self.saved[(service, username)] = password

    def delete_password(self, service, username):
        if self.fail:
            raise RuntimeError("使えない")
        del self.saved[(service, username)]


class ReportTokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        config.save_config({"report_email": "me@example.com"})

    def use_vault(self, vault):
        patcher = mock.patch.object(config, "_vault", return_value=vault)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_saved_in_the_vault_not_in_config_json(self):
        vault = FakeVault()
        self.use_vault(vault)
        config.set_report_token("tok")
        self.assertEqual(config.get_report_token(), "tok")
        self.assertNotIn("report_token", config.load_config())
        self.assertEqual(config.load_config()["report_email"], "me@example.com", "ほかの設定を消してしまう")
        self.assertEqual(list(vault.saved.values()), ["tok"])

        config.clear_report_token()
        self.assertEqual((config.get_report_token(), vault.saved), ("", {}))

    def test_token_of_older_versions_is_moved_to_the_vault(self):
        config.save_config({"report_email": "me@example.com", "report_token": "old"})
        vault = FakeVault()
        self.use_vault(vault)
        self.assertEqual(config.get_report_token(), "old", "移す前でも読める")
        config.migrate_report_token()
        self.assertNotIn("report_token", config.load_config())
        self.assertEqual(config.get_report_token(), "old")

    def test_falls_back_to_config_json(self):
        # macOS など資格情報マネージャーが無いとき・使えないときは、config.json に保存する
        for vault in (None, FakeVault(fail=True)):
            with self.subTest(vault=vault):
                self.use_vault(vault)
                config.set_report_token("tok")
                self.assertEqual(config.load_config()["report_token"], "tok")
                self.assertEqual(config.get_report_token(), "tok")
                config.migrate_report_token()  # 移せなくても消さない
                self.assertEqual(config.get_report_token(), "tok")
                config.clear_report_token()
                self.assertEqual(config.get_report_token(), "")

    @unittest.skipIf(sys.platform == "win32", "Windows ではファイルの権限を使わない")
    def test_config_json_is_readable_only_by_the_user(self):
        config.save_config({"report_token": "tok"})
        self.assertEqual(config.get_config_path().stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(sys.platform == "win32", "Windows の資格情報マネージャーで確かめる")
    def test_real_windows_vault(self):
        # テスト用の一時フォルダごとの名前で保存するので、実際のアプリのトークンには触れない
        self.assertIsNotNone(config._vault(), "keyring を読み込めない（配布版に同梱されないおそれ）")
        config.set_report_token("tok-for-test")
        try:
            self.assertEqual(config.get_report_token(), "tok-for-test")
            self.assertNotIn("report_token", config.load_config())
        finally:
            config.clear_report_token()
        self.assertEqual(config.get_report_token(), "")


if __name__ == "__main__":
    unittest.main()


class ErrorLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logger = logging.getLogger("justdoit.test")
        handler = config.ErrorLogHandler(logging.WARNING)
        self.logger.addHandler(handler)
        self.addCleanup(self.logger.removeHandler, handler)

    def test_only_warnings_are_written(self):
        self.logger.info("記録しました")
        self.logger.warning("通知を出せませんでした")

        text = config.get_error_log_path().read_text(encoding="utf-8")
        self.assertIn("通知を出せませんでした", text)
        # 問い合わせのときに原因を絞り込めるよう、OS も残す
        self.assertIn(config.os_description(), text)
        self.assertNotIn("記録しました", text)

    def test_traceback_is_written(self):
        try:
            raise ValueError("こわれた")
        except ValueError:
            self.logger.exception("予期しないエラーが起きました")

        text = config.get_error_log_path().read_text(encoding="utf-8")
        self.assertIn("Traceback", text)
        self.assertIn("ValueError: こわれた", text)
