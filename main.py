"""Just do it. を起動する（中身は justdoit/ パッケージ）

--self-test を付けると、画面を一通り表示して動作を確かめてから終了する（GitHub Actions でビルド直後に使う）
"""

import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from justdoit import selftest

        sys.exit(selftest.run())

    from justdoit.ui.app import run

    run()
