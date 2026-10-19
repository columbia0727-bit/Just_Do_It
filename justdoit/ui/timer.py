"""集中タイマー・休憩タイマーと、やったことを記録する画面"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import tkinter as tk
from typing import TYPE_CHECKING

from PIL import ImageTk

from justdoit import config, focus
from justdoit.records import (
    RECENT_DAYS,
    empty_records,
    load_records,
    recent_tasks,
    recorded_at_on,
    task_counts,
    validate_record,
)
from justdoit.ui import confirm
from justdoit.ui.datepicker import DatePicker
from justdoit.ui.suggest import TaskSuggestions
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

FOCUS_SHORT_SECONDS = focus.FOCUS_SHORT_SECONDS
TIMER_SIZE = (320, 420)
RECORD_FORM_SIZE = (320, 420)  # 「このまま続ける」のボタンが増えても収まる高さ
MANUAL_RECORD_SIZE = (380, 440)
CONTENT_WIDTH = 272  # 画面の幅から左右の余白を引いた幅
RING_SIZE = 210
RING_THICKNESS = 7


def format_clock(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    return f"{mins:02d}:{secs:02d}"


def make_ring_clock(screen: tk.Frame, total_seconds: int, name: str) -> Callable[[int], None]:
    """残り時間を、数字と円形の進捗リングで表示する。残り秒数を渡して表示を更新する関数を返す

    ウィンドウのタイトルにも「12:34 集中」のように出す（最小化していても、タスクバーなどで残り時間がわかるように）。
    """
    clock = tk.Label(screen, font=ui_font(34), fg=C.text, bg=screen["bg"], compound="center", bd=0)
    clock.pack(pady=(px(8), 0))
    # 表示中の画像を持っておく（Python 側で参照が無くなると、Tk の画像も消えてしまう）
    shown: dict[str, ImageTk.PhotoImage] = {}

    def update(remaining: int) -> None:
        shown["ring"] = ring_image(px(RING_SIZE), remaining / total_seconds, px(RING_THICKNESS))
        clock.config(image=shown["ring"], text=format_clock(remaining))
        screen.winfo_toplevel().title(f"{format_clock(remaining)} {name} - {config.APP_NAME}")

    update(total_seconds)
    return update


def start_countdown(
    app: JustDoItApp,
    total_seconds: int,
    on_tick: Callable[[int], None],
    on_finish: Callable[[], None],
    start: datetime | None = None,
) -> datetime:
    """1秒ごとに on_tick(残り秒数) を呼び、0になったら on_finish を呼ぶ。開始時刻（省略すると今）を返す

    残り時間は開始時刻との差から毎回計算するので、PC がスリープしてもずれない。
    """
    start = start or datetime.now()

    def tick():
        remaining = focus.remaining_seconds(total_seconds, start, datetime.now())
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
    update_clock = make_ring_clock(screen, duration_seconds, "集中")

    def time_up():
        remember_last_seen()
        # 設定画面で選んだ方法で知らせて、そのまま記録画面へ
        # 「5分だけやる」が終わったときは、乗ってきたらそのまま続けられるようにする（このアプリの考え方）
        focus_minutes = config.load_preferences().focus_minutes
        can_continue = focus.can_keep_going(duration_seconds, done_mins, focus_minutes)
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
        # 続けている場合は、それまでの分も足す
        return done_mins + focus.elapsed_minutes(start, datetime.now())

    def finish_early():
        # 途中で終えても、そこまでの時間を記録できる
        remember_last_seen()
        show_record_form(app, elapsed_mins(), after_save=app.show_main_menu)

    def confirm_close() -> bool:
        answer = confirm.ask(
            app,
            "タイマーの途中です",
            f"ここまでの {elapsed_mins()}分を記録しますか？",
            [
                confirm.Choice("記録してから終える", "record"),
                confirm.Choice("記録せずに終了する", "close"),
                confirm.Choice("タイマーを続ける", "continue", safe=True),
            ],
        )
        if answer == "record":
            finish_early()
        elif answer == "close":
            focus.clear_unsaved(config.get_unsaved_timer_path())
        return answer == "close"

    def confirm_quit():
        if confirm.ask(
            app,
            "タイマーをやめますか？",
            f"ここまでの {elapsed_mins()}分は記録されません。",
            [
                confirm.Choice("やめてメニューに戻る", True),
                confirm.Choice("タイマーを続ける", False, safe=True),
            ],
        ):
            focus.clear_unsaved(config.get_unsaved_timer_path())
            app.show_main_menu()

    # アプリや PC が落ちても次に起動したときに記録できるよう、記録するまで開始時刻などを残しておく
    start = datetime.now()
    unsaved = focus.UnsavedTimer(start, start, duration_seconds, done_mins)
    focus.save_unsaved(config.get_unsaved_timer_path(), unsaved)

    def remember_last_seen():
        unsaved.last_seen = datetime.now()
        focus.save_unsaved(config.get_unsaved_timer_path(), unsaved)

    def tick(remaining: int):
        update_clock(remaining)
        if (datetime.now() - unsaved.last_seen).total_seconds() >= focus.HEARTBEAT_SECONDS:
            remember_last_seen()

    make_button(screen, "ここで終える", finish_early).pack(side="bottom", fill="x")

    start_countdown(app, duration_seconds, on_tick=tick, on_finish=time_up, start=start)
    app.close_guard = confirm_close


def show_record_form(
    app: JustDoItApp,
    duration_mins: int,
    after_save: Callable[[], None],
    save_text: str = "記録する",
    on_continue: Callable[[], None] | None = None,
    continue_text: str = "",
    recorded_at: datetime | None = None,
    note: str = "",
) -> None:
    """やったことを入力して記録する画面（タイマー終了時・途中終了時・前回記録しなかったタイマーで共通）

    on_continue を渡すと「このまま続ける」ボタンを出す（記録はせず、続けた分と合わせて最後に記録する）。
    記録する・記録しないを決めたら、保存しておいた記録する前のタイマーを消す。
    """
    screen = app.make_screen(RECORD_FORM_SIZE)

    make_label(screen, "おつかれさまでした", size=16, bold=True).pack(pady=(16, 0))
    make_label(screen, f"{duration_mins}分", size=11, color=C.muted).pack()
    if note:
        make_label(screen, note, size=10, color=C.muted, wraplength=app.px(CONTENT_WIDTH - 8)).pack()

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
        if not app.save_record(task, duration_mins, recorded_at=recorded_at):
            return
        focus.clear_unsaved(config.get_unsaved_timer_path())
        app.bring_to_front(False)
        after_save()

    def skip():
        focus.clear_unsaved(config.get_unsaved_timer_path())
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

    def confirm_close() -> bool:
        if not confirm_discard(app, task_entry):
            return False
        focus.clear_unsaved(config.get_unsaved_timer_path())
        return True

    app.close_guard = confirm_close


def show_unsaved_record(app: JustDoItApp, unsaved: focus.UnsavedTimer) -> None:
    """前回、記録する前にアプリや PC が終了したタイマーを記録する画面（起動したときに出す）

    日時は、最後にアプリが動いていた時刻で記録する。
    """
    when = unsaved.last_seen
    show_record_form(
        app,
        unsaved.minutes(),
        after_save=app.show_main_menu,
        recorded_at=when,
        # 日時の途中（空白）で折り返されないよう、改行する位置を決めておく
        note=f"前回のタイマー（{when.month}/{when.day} {when:%H:%M} ごろまで）が\n記録されていません",
    )


def make_task_input(app: JustDoItApp, screen: tk.Frame, content_width: int = CONTENT_WIDTH) -> tk.Entry:
    """作業内容の入力欄と、その下の「最近やったこと」の候補（押すと入力欄に入る）

    打ち始めると、前に使った名前のうち、打った文字を含むものも候補に出す（名前のばらつきを防ぐため）。
    """
    task_entry = make_entry(screen)
    task_entry.pack(fill="x", ipady=4)
    task_entry.focus_set()

    try:
        records = load_records(config.get_csv_path())
    except (OSError, ValueError):
        records = empty_records()
    TaskSuggestions(task_entry, task_counts(records["作業内容"]))
    tasks = recent_tasks(records)
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
    return confirm.ask(
        app,
        "記録せずに終了しますか？",
        "入力した内容は記録されません。",
        [confirm.Choice("記録せずに終了する", True), confirm.Choice("入力に戻る", False, safe=True)],
    )


# ==========================================
# 休憩タイマー
# ==========================================
def show_break_timer(app: JustDoItApp) -> None:
    break_seconds = config.load_preferences().break_minutes * 60
    screen = app.make_screen(TIMER_SIZE)

    # 集中タイマーと高さをそろえるため、「戻る」の分の余白をとる
    make_label(screen, "休憩", size=11, color=C.muted).pack(pady=(px(28), 0))
    update_clock = make_ring_clock(screen, break_seconds, "休憩")

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
    """タイマーを使わなかった作業を記録する（日付を選べるので、前の日の作業もあとから記録できる）

    時刻は入力しない（振り返り・週次レポートは日ごとに集計するため）。細かく直したいときは記録一覧で直せる。
    """
    screen = app.make_screen(MANUAL_RECORD_SIZE)
    app.make_header(screen, "記録する")

    make_label(screen, "やったこと", size=11).pack(anchor="w", pady=(0, 4))
    task_entry = make_task_input(app, screen, content_width=MANUAL_RECORD_SIZE[0] - 48)

    today = datetime.now().date()
    fields = tk.Frame(screen, bg=screen["bg"])
    fields.pack(anchor="w", pady=(12, 0))
    for column, text in enumerate(["日付", "時間（分）"]):
        make_label(fields, text, size=11).grid(row=0, column=column, sticky="w", padx=(0, 10), pady=(0, 4))
    day_picker = DatePicker(fields, today, first=today - timedelta(days=RECENT_DAYS), last=today)
    day_picker.grid(row=1, column=0, sticky="w", padx=(0, 10))
    mins_entry = make_entry(fields, width=6)
    mins_entry.grid(row=1, column=1, sticky="w", ipady=4)

    error_label = make_label(screen, size=10, color=C.error)
    error_label.pack(anchor="w", pady=(4, 0))

    def save(event=None):
        result = validate_record(task_entry.get(), mins_entry.get())
        if isinstance(result, str):
            error_label.config(text=result)
            (mins_entry if task_entry.get().strip() else task_entry).focus_set()
            return
        if app.save_record(*result, recorded_at=recorded_at_on(day_picker.get(), datetime.now())):
            app.show_main_menu()

    make_button(screen, "記録する", save, primary=True).pack(side="bottom", fill="x")

    # Enterキーで次の欄へ・保存
    task_entry.bind("<Return>", lambda event: mins_entry.focus_set())
    mins_entry.bind("<Return>", save)
    app.close_guard = lambda: confirm_discard(app, task_entry)
