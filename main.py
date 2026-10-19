"""Just do it. を起動する（中身は justdoit/ パッケージ）

--self-test を付けると、画面を一通り表示して動作を確かめてから終了する（GitHub Actions でビルド直後に使う）。
さらに --screenshots フォルダ名 を付けると、各画面のスクリーンショットもそのフォルダに保存する
"""

from pathlib import Path
import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from justdoit import selftest

        screenshot_dir = None
        if "--screenshots" in sys.argv:
            screenshot_dir = Path(sys.argv[sys.argv.index("--screenshots") + 1])
        sys.exit(selftest.run(screenshot_dir=screenshot_dir))

    from justdoit.ui.app import run

    run()
