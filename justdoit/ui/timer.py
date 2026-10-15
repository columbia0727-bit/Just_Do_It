"""集中タイマー・休憩タイマーと、やったことを記録する画面"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

from PIL import ImageTk

from justdoit import config
from justdoit.records import RECENT_DAYS, load_records, recent_tasks, validate_record, validate_when
from justdoit.ui.datepicker import DatePicker
from justdoit.ui.theme import (
    C,
    make_back_button,
    make_button,
    make_chips,
    make_entry,
    make_label,
    make_link,
    px,
    ring_image,
    ui_font,
)

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

FOCUS_SHORT_SECONDS = 5 * 60
TIMER_SIZE = (320, 420)
RECORD_FORM_SIZE = (320, 400)
MANUAL_RECORD_SIZE = (380, 440)
CONTENT_WIDTH = 272  # 画面の幅から左右の余白を引いた幅
RING_SIZE = 210
RING_THICKNESS = 7


def format_clock(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    return f"{mins:02d}:{secs:02d}"


def make_ring_clock(screen: tk.Frame, total_seconds: int) -> Callable[[int], None]:
    """残り時間を、数字と円形の進捗リングで表示する。残り秒数を渡して表示を更新する関数を返す"""
    clock = tk.Label(screen, font=ui_font(34), fg=C.text, bg=screen["bg"], compound="center", bd=0)
    clock.pack(pady=(px(8), 0))
    # 表示中の画像を持っておく（Python 側で参照が無くなると、Tk の画像も消えてしまう）
    shown: dict[str, ImageTk.PhotoImage] = {}

    def update(remaining: int) -> None:
        shown["ring"] = ring_image(px(RING_SIZE), remaining / total_seconds, px(RING_THICKNESS))
        clock.config(image=shown["ring"], text=format_clock(remaining))

    update(total_seconds)
    return update


def start_countdown(
    app: JustDoItApp, total_seconds: int, on_tick: Callable[[int], None], on_finish: Callable[[], None]
) -> datetime:
    """1秒ごとに on_tick(残り秒数) を呼び、0になったら on_finish を呼ぶ。開始時刻を返す

    残り時間は開始時刻との差から毎回計算するので、PC がスリープしてもずれない。
    """
    start = datetime.now()

    def tick():
        remaining = total_seconds - int((datetime.now() - start).total_seconds())
        if remaining > 0:
            on_tick(remaining)
            app.schedule(1000, tick)
        else:
            on_finish()

    tick()
    return start


# ==========================================
# 集中タイマー
# ==========================================
def show_focus_timer(app: JustDoItApp, duration_seconds: int, done_mins: int = 0) -> None:
    """集中タイマー。done_mins は、続けてやっている場合のそれまでの分（最後にまとめて記録する）"""
    duration_mins = duration_seconds // 60
    total_mins = done_mins + duration_mins
    screen = app.make_screen(TIMER_SIZE)

    # 「ここで終える」と押し間違えないよう、やめる操作は右上に離して置く
    top = tk.Frame(screen, bg=screen["bg"])
    top.pack(fill="x")
    make_back_button(top, lambda: confirm_quit()).pack(side="right")

    title = f"集中（あと{duration_mins}分・合計{total_mins}分）" if done_mins else f"集中（{duration_mins}分）"
    make_label(screen, title, size=11, color=C.muted).pack()
    update_clock = make_ring_clock(screen, duration_seconds)

    def time_up():
        # 設定画面で選んだ方法で知らせて、そのまま記録画面へ
        # 「5分だけやる」が終わったときは、乗ってきたらそのまま続けられるようにする（このアプリの考え方）
        focus_minutes = config.load_preferences().focus_minutes
        can_continue = not done_mins and duration_seconds == FOCUS_SHORT_SECONDS and focus_minutes > duration_mins
        extra_mins = focus_minutes - duration_mins
        message = "このまま続けることもできます。" if can_continue else "やったことを記録しましょう。"
        app.notify("集中タイム終了", f"{total_mins}分おつかれさまでした。{message}")

        def keep_going():
            show_focus_timer(app, extra_mins * 60, done_mins=total_mins)

        show_record_form(
            app,
            total_mins,
            after_save=lambda: show_break_timer(app),
            save_text="記録して休憩する",
            on_continue=keep_going if can_continue else None,
            continue_text=f"このまま続ける（あと{extra_mins}分）",
        )

    def elapsed_mins() -> int:
        # 1分未満でも最低「1分」として切り上げる（続けている場合は、それまでの分も足す）
        elapsed_secs = int((datetime.now() - start).total_seconds())
        return done_mins + max(1, (elapsed_secs + 59) // 60)

    def finish_early():
        # 途中で終えても、そこまでの時間を記録できる
        show_record_form(app, elapsed_mins(), after_save=app.show_main_menu)

    def confirm_close() -> bool:
        answer = messagebox.askyesnocancel(
            "タイマーの途中です",
            f"ここまでの {elapsed_mins()}分を記録しますか？\n\n"
            "はい：記録画面へ進む\nいいえ：記録せずに終了する\nキャンセル：タイマーを続ける",
            parent=app.root,
        )
        if answer:
            finish_early()
        return answer is False

    def confirm_quit():
        if messagebox.askyesno(
            "タイマーをやめる",
            f"ここまでの {elapsed_mins()}分は記録されません。\nタイマーをやめてメニューに戻りますか？",
            parent=app.root,
        ):
            app.show_main_menu()

    make_button(screen, "ここで終える", finish_early).pack(side="bottom", fill="x")

    start = start_countdown(app, duration_seconds, on_tick=update_clock, on_finish=time_up)
    app.close_guard = confirm_close


def show_record_form(
    app: JustDoItApp,
    duration_mins: int,
    after_save: Callable[[], None],
    save_text: str = "記録する",
    on_continue: Callable[[], None] | None = None,
    continue_text: str = "",
) -> None:
    """やったことを入力して記録する画面（タイマー終了時・途中終了時で共通）

    on_continue を渡すと「このまま続ける」ボタンを出す（記録はせず、続けた分と合わせて最後に記録する）。
    """
    screen = app.make_screen(RECORD_FORM_SIZE)

    make_label(screen, "おつかれさまでした", size=16, bold=True).pack(pady=(16, 0))
    make_label(screen, f"{duration_mins}分", size=11, color=C.muted).pack()

    make_label(screen, "何をやった？", size=11).pack(anchor="w", pady=(20, 4))
    task_entry = make_task_input(app, screen)
    error_label = make_label(screen, size=10, color=C.error)
    error_label.pack(anchor="w")

    def save(event=None):
        task = task_entry.get().strip()
        if not task:
            error_label.config(text="やったことを入力してください")
            return
        # 保存できなかったときは入力した内容を残したまま、この画面にとどまる
        if not app.save_record(task, duration_mins):
            return
        app.bring_to_front(False)
        after_save()

    def skip():
        app.bring_to_front(False)
        app.show_main_menu()

    def keep_going():
        app.bring_to_front(False)
        if on_continue:
            on_continue()

    # 下にまとめて置き、上から順に作る（Tab キーで選ぶ順を、見た目の順にそろえるため）
    actions = tk.Frame(screen, bg=C.bg)
    actions.pack(side="bottom", fill="x")
    if on_continue:
        make_button(actions, continue_text, keep_going).pack(fill="x", pady=(0, 8))
    make_button(actions, save_text, save, primary=True).pack(fill="x")
    make_link(actions, "記録しない", skip).pack(pady=(10, 0))
    task_entry.bind("<Return>", save)
    app.close_guard = lambda: confirm_discard(app, task_entry)


def make_task_input(app: JustDoItApp, screen: tk.Frame, content_width: int = CONTENT_WIDTH) -> tk.Entry:
    """作業内容の入力欄と、その下の「最近やったこと」の候補（押すと入力欄に入る）"""
    task_entry = make_entry(screen)
    task_entry.pack(fill="x", ipady=4)
    task_entry.focus_set()

    try:
        tasks = recent_tasks(load_records(config.get_csv_path()))
    except (OSError, ValueError):
        tasks = []
    if tasks:

        def fill(task: str):
            task_entry.delete(0, "end")
            task_entry.insert(0, task)
            task_entry.focus_set()

        make_chips(screen, tasks, fill, max_width=app.px(content_width)).pack(anchor="w", pady=(6, 0))
    return task_entry


def confirm_discard(app: JustDoItApp, task_entry: tk.Entry) -> bool:
    """入力の途中で閉じようとしたときの確認（何も入力していなければそのまま閉じる）"""
    if not task_entry.get().strip():
        return True
    return messagebox.askyesno("終了の確認", "入力した内容を記録せずに終了しますか？", parent=app.root)


# ==========================================
# 休憩タイマー
# ==========================================
def show_break_timer(app: JustDoItApp) -> None:
    break_seconds = config.load_preferences().break_minutes * 60
    screen = app.make_screen(TIMER_SIZE)

    # 集中タイマーと高さをそろえるため、「戻る」の分の余白をとる
    make_label(screen, "休憩", size=11, color=C.muted).pack(pady=(px(28), 0))
    update_clock = make_ring_clock(screen, break_seconds)

    make_button(screen, "休憩を終える", app.show_main_menu).pack(side="bottom", fill="x")

    def break_over():
        # 知らせてメニューへ戻る（前面に出すのは一瞬だけ）
        app.notify("休憩終了", "休憩おわり。次の作業を始めましょう。")
        app.show_main_menu()
        app.bring_to_front(False)

    start_countdown(app, break_seconds, on_tick=update_clock, on_finish=break_over)


# ==========================================
# 手動記録（タイマーを使わなかった作業を後から追加する）
# ==========================================
def show_manual_record(app: JustDoItApp) -> None:
    """タイマーを使わなかった作業を記録する（日付と時刻も選べるので、前の日の作業もあとから記録できる）"""
    screen = app.make_screen(MANUAL_RECORD_SIZE)
    app.make_header(screen, "記録する")

    make_label(screen, "やったこと", size=11).pack(anchor="w", pady=(0, 4))
    task_entry = make_task_input(app, screen, content_width=MANUAL_RECORD_SIZE[0] - 48)

    now = datetime.now()
    today = now.date()
    fields = tk.Frame(screen, bg=screen["bg"])
    fields.pack(anchor="w", pady=(12, 0))
    for column, text in enumerate(["日付", "時刻", "時間（分）"]):
        make_label(fields, text, size=11).grid(row=0, column=column, sticky="w", padx=(0, 10), pady=(0, 4))
    day_picker = DatePicker(fields, today, first=today - timedelta(days=RECENT_DAYS), last=today)
    day_picker.grid(row=1, column=0, sticky="w", padx=(0, 10))
    time_entry = make_entry(fields, width=6)
    time_entry.insert(0, f"{now:%H:%M}")
    time_entry.grid(row=1, column=1, sticky="w", padx=(0, 10), ipady=4)
    mins_entry = make_entry(fields, width=6)
    mins_entry.grid(row=1, column=2, sticky="w", ipady=4)

    error_label = make_label(screen, size=10, color=C.error)
    error_label.pack(anchor="w", pady=(4, 0))

    def save(event=None):
        result = validate_record(task_entry.get(), mins_entry.get())
        if isinstance(result, str):
            error_label.config(text=result)
            (mins_entry if task_entry.get().strip() else task_entry).focus_set()
            return
        when = validate_when(f"{day_picker.get():%Y/%m/%d}", time_entry.get())
        if isinstance(when, str):
            error_label.config(text=when)
            time_entry.focus_set()
            return
        if app.save_record(*result, recorded_at=when):
            app.show_main_menu()

    make_button(screen, "記録する", save, primary=True).pack(side="bottom", fill="x")

    # Enterキーで次の欄へ・保存
    task_entry.bind("<Return>", lambda event: mins_entry.focus_set())
    mins_entry.bind("<Return>", save)
    time_entry.bind("<Return>", save)
    app.close_guard = lambda: confirm_discard(app, task_entry)
