from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_DIR = Path(__file__).resolve().parent.parent


class SelfTestTest(unittest.TestCase):
    """main.py --self-test（すべての画面を一度ずつ表示する動作確認）がエラーなく通ること

    画面を持たない処理の単体テストでは見つからない、画面を作る途中のエラーを見つけるため。
    別のプロセスで動かすので、動作確認用のサンプルの記録がほかのテストに影響しない。
    """

    def test_every_screen_opens_without_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(PROJECT_DIR / "main.py"), "--self-test"],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            log = (Path(tmp) / "selftest.log").read_text(encoding="utf-8")
        if "SKIPPED" in log:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        self.assertEqual(result.returncode, 0, log)
        self.assertIn("RESULT: OK", log)

    def test_screenshots_are_saved(self):
        """--screenshots を付けると、全画面（ライト・ダーク）のスクリーンショットを保存する"""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(PROJECT_DIR / "main.py"), "--self-test", "--screenshots", "shots"],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            log = (Path(tmp) / "selftest.log").read_text(encoding="utf-8")
            shots = sorted((Path(tmp) / "shots").glob("*.png"))
        if "SKIPPED" in log:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        if "スクリーンショットを撮れませんでした" in log:
            self.skipTest("この環境では画面を撮れない（動作確認そのものは失敗にしない）")
        self.assertEqual(result.returncode, 0, log)
        screens = log.count("[light] ")
        self.assertEqual(len(shots), screens * 2, [shot.name for shot in shots])


if __name__ == "__main__":
    unittest.main()
