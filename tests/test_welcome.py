from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import config, records  # noqa: E402
from justdoit.ui import app  # noqa: E402


class FirstLaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "get_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_launch_only_until_welcomed(self):
        self.assertTrue(app.is_first_launch())
        app.mark_welcomed()
        self.assertFalse(app.is_first_launch())

    def test_not_shown_to_people_who_already_have_records(self):
        # 以前のバージョンから更新した人には、案内を出さない
        records.append_record_to_csv(config.get_csv_path(), "2026-10-13 09:00:00", "読書", 20)
        self.assertFalse(app.is_first_launch())

    def test_welcomed_keeps_other_settings(self):
        config.save_config({"report_token": "tok"})
        app.mark_welcomed()
        self.assertEqual(config.load_config(), {"report_token": "tok", "welcomed": True})


if __name__ == "__main__":
    unittest.main()
