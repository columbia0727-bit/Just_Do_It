"""README 用のスクリーンショット（docs/*.png）を、サンプルの記録で撮り直す

本物の記録・設定には触れず、一時フォルダにサンプルの記録を作って各画面を表示し、ウィンドウの中身を撮る。
画面を変えたあと、README の画像を同じ条件でそろえて撮り直すために使う（週次レポートのメールの画像は対象外）。

    python tools/readme_screenshots.py            # docs/ に保存する
    python tools/readme_screenshots.py 保存先      # 確かめたいときは、別のフォルダに保存する

Mac では、ターミナル（または Python）に「画面収録」の許可が要る。撮っている間は、ほかのウィンドウを重ねない。
"""

from collections.abc import Callable
from datetime import datetime, timedelta
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import tkinter as tk

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image, ImageGrab  # noqa: E402

from justdoit import config, records, updates  # noqa: E402

TASKS = ["ポートフォリオ制作", "資格の勉強", "英語の勉強", "メール返信", "読書"]
WEEKLY_GOAL_MINUTES = 5 * 60
TIMER_REMAINING_SECONDS = 15 * 60 + 39  # タイマーの画面で止めておく残り時間（15:39）
SETTLE_MS = 700  # 画面を出してから撮るまで待つ時間
# 保存する画像の倍率（画面の大きさに対して）。Mac は2倍で撮れるが、README の表で大きくなりすぎないよう縮める
OUTPUT_SCALE = 1.25


def write_sample_records(csv_path: Path, today: datetime) -> None:
    """約50日分のサンプルの記録（今日まで13日連続・今日は50分）。毎回同じ記録になるよう、乱数の種を決めておく"""
    rng = random.Random(7)
    for days_ago in range(50, -1, -1):
        day = today - timedelta(days=days_ago)
        if days_ago == 0:
            entries = [(10, "英語の勉強", 25), (14, "ポートフォリオ制作", 25)]
        elif days_ago == 13 or (days_ago > 13 and rng.random() < 0.15):
            continue  # 記録しなかった日（今日までの連続を13日にする）
        else:
            hours = sorted(rng.sample(range(9, 21), rng.randint(2, 5)))
            entries = [(hour, rng.choice(TASKS), rng.choice([5, 15, 25, 25, 25, 30, 50])) for hour in hours]
        for hour, task, minutes in entries:
            when = day.replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0)
            records.append_record_to_csv(csv_path, when.strftime(records.DATETIME_FORMAT), task, minutes)


class FrozenClock(datetime):
    """タイマーの画面を、残り時間を止めた状態で撮るための時計

    最初に聞かれた時刻（タイマーの開始）から、それ以降はずっと TIMER_REMAINING_SECONDS が残る時刻を返す。
    """

    started: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        if cls.started is None:
            cls.started = datetime.now()
            return cls.started
        return cls.started + timedelta(seconds=25 * 60 - TIMER_REMAINING_SECONDS)


def find_widgets(widget: tk.Misc, kind: type) -> list:
    found = [widget] if isinstance(widget, kind) else []
    for child in widget.winfo_children():
        found.extend(find_widgets(child, kind))
    return found


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    config.get_data_dir = lambda: tmp
    updates.check_for_update = lambda: None
    write_sample_records(config.get_csv_path(), datetime.now())
    config.save_preferences(config.Preferences(weekly_goal_minutes=WEEKLY_GOAL_MINUTES, appearance="light"))

    from justdoit.ui import app as app_module
    from justdoit.ui import dashboard, history, settings, timer
    from justdoit.ui.datepicker import DatePicker

    root = tk.Tk()
    app = app_module.JustDoItApp(root)
    # ほかのウィンドウに隠れていると、その上から撮ってしまうので、いちばん前に出しておく
    root.attributes("-topmost", True)
    if sys.platform == "darwin":
        script = 'tell application "System Events" to set frontmost of (first process whose unix id is {}) to true'
        subprocess.run(["osascript", "-e", script.format(os.getpid())], capture_output=True)
    root.focus_force()

    def set_appearance(appearance: str) -> None:
        config.save_preferences(config.Preferences(weekly_goal_minutes=WEEKLY_GOAL_MINUTES, appearance=appearance))

    def show_timer(appearance: str) -> Callable[[], None]:
        def show() -> None:
            set_appearance(appearance)
            FrozenClock.started = None
            timer.datetime = FrozenClock  # type: ignore[misc]
            timer.show_focus_timer(app, 25 * 60)

        return show

    def show_history() -> None:
        history.show_history(app, back=app.show_main_menu)
        root.update()
        table = find_widgets(root, history.ttk.Treeview)[0]
        table.selection_set(table.get_children()[1])
        table.event_generate("<<TreeviewSelect>>")

    def show_calendar() -> None:
        timer.show_manual_record(app)
        root.update()
        find_widgets(root, tk.Entry)[0].insert(0, "読書")
        find_widgets(root, DatePicker)[0].open()

    def show_settings() -> None:
        settings.show_settings(app, "timer")
        root.update()
        # 保存先は、一時フォルダではなく、配布版を使ったときの場所を見せる
        for label in find_widgets(root, tk.Label):
            if str(label.cget("text")).startswith("保存先:"):
                label.config(text="保存先: ~/Library/Application Support/JustDoIt")

    shots: list[tuple[str, Callable[[], None]]] = [
        ("menu", app.show_main_menu),
        ("timer", show_timer("light")),
        ("dashboard", lambda: dashboard.show_dashboard(app, "week")),
        ("record", lambda: timer.show_record_form(app, 25, after_save=app.show_main_menu)),
        ("history", show_history),
        ("calendar", show_calendar),
        ("settings", show_settings),
        ("dark", show_timer("dark")),
    ]

    def take(index: int) -> None:
        if index == len(shots):
            app.close_guard = None
            root.destroy()
            return
        name, show = shots[index]
        timer.datetime = datetime  # type: ignore[misc]
        set_appearance("light")
        show()

        def grab() -> None:
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            width, height = root.winfo_width(), root.winfo_height()
            image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            size = (round(width * OUTPUT_SCALE), round(height * OUTPUT_SCALE))
            path = out_dir / f"{name}.png"
            image = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
            # 画面の色は少ないので、256色にしてファイルを小さくする（見た目はほぼ変わらない）
            image = image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            image.save(path, optimize=True)
            print(f"{path}（{size[0]}x{size[1]}）")
            take(index + 1)

        root.after(SETTLE_MS, grab)

    root.after(SETTLE_MS, lambda: take(0))
    root.mainloop()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_DIR / "docs")
