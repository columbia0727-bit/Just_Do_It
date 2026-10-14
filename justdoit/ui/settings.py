"""設定画面（「全般」（表示・タイマー・知らせ方）と「週次レポート」の2つのタブ）"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import platform
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import TYPE_CHECKING, Callable

from justdoit import config, report_service
from justdoit.records import load_records
from justdoit.report_service import ReportServiceError
from justdoit.ui import theme
from justdoit.ui.theme import (
    C,
    make_button,
    make_checkbox,
    make_entry,
    make_label,
    make_link,
    make_select,
    make_tabs,
)

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

SETTINGS_SIZE = (460, 560)
TEXT_WIDTH = 410  # 折り返す文章の幅
TABS = [("timer", "全般"), ("report", "週次レポート")]

# on_done(result, error): 成功なら result に結果、失敗なら error に例外が入る
OnDone = Callable[[dict | None, ReportServiceError | None], None]


def show_settings(app: JustDoItApp, tab: str | None = None) -> None:
    if tab:
        app.settings_tab = tab
    screen = app.make_screen(SETTINGS_SIZE)
    header = app.make_header(screen, "設定")
    make_tabs(
        header,
        TABS,
        app.settings_tab,
        # 通信中はタブも切り替えない（戻るボタンと同じ理由）
        lambda key: app.busy or show_settings(app, key),
    ).pack(side="left", padx=(app.px(16), 0))

    build_data_folder(app, screen)
    if app.settings_tab == "timer":
        build_timer_section(app, screen)
    else:
        build_report_section(app, screen)


def build_data_folder(app: JustDoItApp, screen: tk.Frame) -> None:
    """画面の一番下: 作業ログの保存先と「フォルダを開く」"""
    footer = tk.Frame(screen, bg=screen["bg"])
    footer.pack(side="bottom", fill="x")
    make_label(
        footer,
        f"保存先: {config.get_data_dir()}",
        size=9,
        color=C.muted,
        wraplength=app.px(TEXT_WIDTH - 90),
        justify="left",
    ).pack(side="left", anchor="w")
    make_link(footer, "フォルダを開く", lambda: open_folder(app, config.get_data_dir())).pack(side="right")


def open_folder(app: JustDoItApp, path: Path) -> None:
    """エクスプローラー（Mac は Finder）でフォルダを開く"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as e:
        messagebox.showerror("エラー", f"フォルダを開けませんでした:\n{e}", parent=app.root)


# ==========================================
# 全般タブ（変えるとすぐ保存する）
# ==========================================
def build_timer_section(app: JustDoItApp, screen: tk.Frame) -> None:
    prefs = config.load_preferences()

    def change(**values):
        nonlocal prefs
        prefs = replace(prefs, **values)
        try:
            config.save_preferences(prefs)
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)

    def change_appearance(index: int):
        change(appearance=theme.APPEARANCE_CHOICES[index][0])
        show_settings(app)  # 新しい色で作り直す

    rows = tk.Frame(screen, bg=screen["bg"])
    rows.pack(anchor="w")
    make_label(rows, "表示", bold=True).grid(row=0, column=0, columnspan=2, sticky="w")
    make_label(rows, "画面の色", size=11).grid(row=1, column=0, sticky="w", pady=3)
    make_select(
        rows,
        [label for _, label in theme.APPEARANCE_CHOICES],
        [key for key, _ in theme.APPEARANCE_CHOICES].index(prefs.appearance),
        change_appearance,
        width=16,
    ).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=3)

    make_label(rows, "タイマー", bold=True).grid(row=2, column=0, columnspan=2, sticky="w", pady=(16, 0))
    for row, (label, choices, current, key) in enumerate(
        [
            ("集中する長さ", config.FOCUS_MINUTE_CHOICES, prefs.focus_minutes, "focus_minutes"),
            ("休憩の長さ", config.BREAK_MINUTE_CHOICES, prefs.break_minutes, "break_minutes"),
        ],
        start=3,
    ):
        make_label(rows, label, size=11).grid(row=row, column=0, sticky="w", pady=3)
        make_select(
            rows,
            [f"{mins}分" for mins in choices],
            choices.index(current),
            lambda index, choices=choices, key=key: change(**{key: choices[index]}),
        ).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
    make_label(screen, "「5分だけやる」はいつでも5分です。", size=10, color=C.muted).pack(anchor="w", pady=(2, 0))

    make_label(screen, "終わったときの知らせ方", bold=True).pack(anchor="w", pady=(18, 4))
    for text, key in [
        ("音を鳴らす", "notify_sound"),
        ("ウィンドウを前面に出す", "notify_front"),
        ("OS の通知を出す（画面の隅にお知らせが表示されます）", "notify_os"),
    ]:
        make_checkbox(screen, text, getattr(prefs, key), lambda checked, key=key: change(**{key: checked})).pack(
            anchor="w"
        )

    def try_notify():
        app.notify("Just do it.", "通知のテストです。タイマーが終わるとこのように知らせます。", prefs)
        # 前面に出したままにならないよう、少ししたら元に戻す（画面を移っても必ず戻す）
        app.root.after(1500, lambda: app.bring_to_front(False))

    make_link(screen, "試しに知らせてみる", try_notify).pack(anchor="w", pady=(6, 0))


# ==========================================
# 週次レポートタブ
# ==========================================
def build_report_section(app: JustDoItApp, frame: tk.Frame) -> None:
    """週次レポート欄（登録状態に応じて、登録フォームか配信停止ボタンを出す）"""
    make_label(frame, "週次レポート", bold=True).pack(anchor="w")
    make_label(
        frame, "選んだ曜日・時刻に、1週間の振り返りがメールで届きます。", size=10, color=C.muted
    ).pack(anchor="w", pady=(2, 8))

    if not report_service.get_service_url():
        make_label(
            frame,
            "このビルドでは配信サービスが設定されていません。\n（開発者向け: README の「週次レポート配信サービス」を参照）",
            size=10,
            color=C.muted,
            wraplength=app.px(TEXT_WIDTH),
            justify="left",
        ).pack(anchor="w")
        return

    settings = config.load_config()
    if settings.get("report_token"):
        make_label(frame, f"登録中: {settings.get('report_email', '')}", size=11).pack(anchor="w")
        # 登録後は、選び直すとすぐサーバーに反映する
        status = make_label(frame, size=10, color=C.muted)
        picker = SchedulePicker(app, frame, report_service.get_schedule(settings))
        picker.on_change = lambda: update_schedule(app, picker, status)
        picker.frame.pack(anchor="w", pady=(8, 0))
        status.pack(anchor="w")
        make_button(frame, "配信を停止する", lambda: unregister(app)).pack(fill="x", pady=(8, 0))
        return

    picker = SchedulePicker(app, frame, report_service.get_schedule(settings))
    picker.frame.pack(anchor="w", pady=(0, 8))
    make_label(frame, "メールアドレス", size=11).pack(anchor="w", pady=(0, 4))
    email_entry = make_entry(frame)
    email_entry.pack(fill="x", ipady=4)
    email_entry.focus_set()

    def on_register(event=None):
        register(app, email_entry.get(), picker.get())

    make_button(frame, "確認コードを送る", on_register, primary=True).pack(fill="x", pady=(8, 0))
    email_entry.bind("<Return>", on_register)


class SchedulePicker:
    """「届くタイミング [月曜 ▼] [9時 ▼]」の選択欄"""

    def __init__(self, app: JustDoItApp, parent: tk.Widget, schedule: tuple[int, int]):
        self.on_change: Callable[[], None] | None = None
        self.saved = schedule  # 最後にサーバーへ保存できたタイミング（失敗したら戻す）

        self.frame = tk.Frame(parent, bg=parent["bg"])
        make_label(self.frame, "届くタイミング", size=11).pack(side="left", padx=(0, 10))
        weekday, hour = schedule
        self.weekday = make_select(
            self.frame, [f"{name}曜" for name in report_service.WEEKDAY_NAMES], weekday, self._changed, width=5
        )
        self.hour = make_select(
            self.frame,
            [f"{hour}時" for hour in report_service.REPORT_HOURS],
            report_service.REPORT_HOURS.index(hour),
            self._changed,
            width=5,
        )
        self.weekday.pack(side="left", padx=(0, 6))
        self.hour.pack(side="left")

    def _changed(self, index: int) -> None:
        if self.on_change:
            self.on_change()

    def get(self) -> tuple[int, int]:
        return self.weekday.current(), report_service.REPORT_HOURS[self.hour.current()]

    def set(self, schedule: tuple[int, int]) -> None:
        weekday, hour = schedule
        self.weekday.current(weekday)
        self.hour.current(report_service.REPORT_HOURS.index(hour))


# ==========================================
# 配信サービスとの通信（画面を固めないよう別スレッドで行う）
# ==========================================
def call_service_async(app: JustDoItApp, payload: dict, on_done: OnDone) -> None:
    """配信サービスを別スレッドで呼び出し、終わったら on_done(result, error) を画面のスレッドで呼ぶ

    通信に数秒〜数十秒かかっても画面が固まらないようにする。
    通信中はカーソルを待機表示にし、二重に送信したり設定画面から離れたりできないようにする。
    """
    if app.busy:
        return
    app.busy = True
    app.root.config(cursor="watch")
    url = report_service.get_service_url()
    results: queue.SimpleQueue = queue.SimpleQueue()

    def worker():
        try:
            results.put((report_service.call_service(url, payload), None))
        except ReportServiceError as e:
            results.put((None, e))

    # Tk は別スレッドから触れないため、結果はキュー経由で受け取る
    def wait_result():
        try:
            result, error = results.get_nowait()
        except queue.Empty:
            app.root.after(100, wait_result)
            return
        app.busy = False
        app.root.config(cursor="")
        on_done(result, error)

    threading.Thread(target=worker, daemon=True).start()
    wait_result()


# ==========================================
# 登録（メールアドレス → 確認コード → 登録完了）
# ==========================================
def register(app: JustDoItApp, email: str, schedule: tuple[int, int]) -> None:
    email = email.strip()
    if "@" not in email:
        messagebox.showwarning("入力エラー", "メールアドレスを入力してください。", parent=app.root)
        return

    def on_sent(result, error):
        if error:
            messagebox.showerror("送信エラー", str(error), parent=app.root)
            return
        ask_verify_code(app, email, schedule)

    call_service_async(app, {"action": "register", "email": email}, on_sent)


def ask_verify_code(app: JustDoItApp, email: str, schedule: tuple[int, int]) -> None:
    code = simpledialog.askstring(
        "確認コード",
        f"{email} に届いた6桁の確認コードを入力してください。\n（迷惑メールフォルダに届く場合があります）",
        parent=app.root,
    )
    if code is None:
        return

    def on_verified(result, error):
        if error:
            messagebox.showerror("確認エラー", str(error), parent=app.root)
            # コードの打ち間違いは、その場で入力し直せるようにする
            if error.code == "invalid_code":
                ask_verify_code(app, email, schedule)
            return
        # サーバーに保存されたタイミングを使う（返ってこない古いサーバーなら、選んだタイミング）
        saved = (result.get("weekday", schedule[0]), result.get("hour", schedule[1]))
        finish_register(app, email, result["token"], saved)

    weekday, hour = schedule
    call_service_async(
        app,
        {"action": "verify", "email": email, "code": code.strip(), "weekday": weekday, "hour": hour},
        on_verified,
    )


def finish_register(app: JustDoItApp, email: str, token: str, schedule: tuple[int, int]) -> None:
    settings = config.load_config()
    settings["report_email"] = email
    settings["report_token"] = token
    report_service.save_schedule(settings, *schedule)
    try:
        config.save_config(settings)
    except OSError as e:
        messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)
        return

    # 登録前の記録も送っておき、最初のレポートから中身が入るようにする
    csv_path = config.get_csv_path()
    if csv_path.exists():
        try:
            report_service.enqueue_logs(
                config.get_report_queue_path(), report_service.build_backfill_logs(load_records(csv_path))
            )
        except (OSError, ValueError) as e:
            print(f"⚠️ 過去の記録を送信できませんでした: {e}")
    report_service.start_sync()

    messagebox.showinfo(
        "登録完了",
        f"登録が完了しました。\n{report_service.format_schedule(*schedule)}、1週間の振り返りレポートがメールで届きます。",
        parent=app.root,
    )
    show_settings(app)


# ==========================================
# 届くタイミングの変更
# ==========================================
def update_schedule(app: JustDoItApp, picker: SchedulePicker, status: tk.Label) -> None:
    # 前の変更を送っている途中なら、選び直しは受け付けない
    if app.busy:
        picker.set(picker.saved)
        return
    weekday, hour = picker.get()
    status.config(text="変更しています…")

    def on_done(result, error):
        if error:
            picker.set(picker.saved)
            status.config(text="")
            messagebox.showerror("変更エラー", str(error), parent=app.root)
            return
        picker.saved = (weekday, hour)
        settings = config.load_config()
        report_service.save_schedule(settings, weekday, hour)
        try:
            config.save_config(settings)
        except OSError as e:
            print(f"⚠️ 届くタイミングを保存できませんでした: {e}")
        status.config(text=f"{report_service.format_schedule(weekday, hour)}に届くよう変更しました")

    token = config.load_config().get("report_token")
    call_service_async(
        app, {"action": "update_schedule", "token": token, "weekday": weekday, "hour": hour}, on_done
    )


# ==========================================
# 配信停止
# ==========================================
def unregister(app: JustDoItApp) -> None:
    if not messagebox.askyesno(
        "配信停止",
        "週次レポートの配信を停止しますか？\nサーバーに保存された作業記録も削除されます（アプリ内の記録は残ります）。",
        parent=app.root,
    ):
        return

    def on_done(result, error):
        # すでにサーバー側で解除済み（unauthorized）なら、そのままアプリ側も解除する
        if error and error.code != "unauthorized":
            messagebox.showerror(
                "停止エラー",
                f"{error}\n時間をおいて再度お試しいただくか、レポートメール内のリンクから停止してください。",
                parent=app.root,
            )
            return
        try:
            report_service.clear_registration()
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)
            return
        show_settings(app)

    call_service_async(
        app, {"action": "unregister", "token": config.load_config().get("report_token")}, on_done
    )
