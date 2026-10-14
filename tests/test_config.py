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


if __name__ == "__main__":
    unittest.main()
