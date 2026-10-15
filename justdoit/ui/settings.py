"""設定画面（「全般」（表示・タイマー・知らせ方）と「週次レポート」の2つのタブ）"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import TYPE_CHECKING
import webbrowser

from justdoit import __version__, config, report_service
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
    def switch_tab(key: str) -> None:
        # 通信中はタブも切り替えない（戻るボタンと同じ理由）
        if not app.busy:
            show_settings(app, key)

    make_tabs(header, TABS, app.settings_tab, switch_tab).pack(side="left", padx=(app.px(16), 0))

    folder = build_data_folder(app, screen)
    version = build_version(app, screen)
    if app.settings_tab == "timer":
        build_timer_section(app, screen)
    else:
        build_report_section(app, screen)
    # 下の欄は、ほかの欄に押し出されないよう先に作っている。Tab キーでは見た目どおり最後に選ばれるよう、
    # 重なり順を上げる（Tab で選ぶ順は、この重なり順）
    version.lift()
    folder.lift()


def build_version(app: JustDoItApp, screen: tk.Frame) -> tk.Frame:
    """保存先の上: 今のバージョンと、新しいバージョンがあればダウンロードページへの案内"""
    row = tk.Frame(screen, bg=screen["bg"])
    row.pack(side="bottom", fill="x", pady=(0, app.px(6)))
    make_label(row, f"バージョン {__version__}", size=9, color=C.muted).pack(side="left")
    if app.new_release:
        release = app.new_release
        make_link(
            row, f"新しいバージョン {release.version} をダウンロード", lambda: webbrowser.open(release.url), accent=True
        ).pack(side="right")
    return row


def build_data_folder(app: JustDoItApp, screen: tk.Frame) -> tk.Frame:
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
    return footer


def open_folder(app: JustDoItApp, path: Path) -> None:
    """エクスプローラー（Mac は Finder）でフォルダを開く"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        # sys.platform で分ける（mypy が OS ごとに見分け、Windows にしかない os.startfile をエラーにしないように）
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
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

    def choose_minutes(key: str, choices: tuple[int, ...], index: int) -> None:
        change(**{key: choices[index]})

    def toggle(key: str, checked: bool) -> None:
        change(**{key: checked})

    rows = tk.Frame(screen, bg=screen["bg"])
    rows.pack(anchor="w")
    make_label(rows, "表示", bold=True).grid(row=0, column=0, columnspan=2, sticky="w")
    make_label(rows, "画面の色", size=11).grid(row=1, column=0, sticky="w", pady=3)
    make_select(
        rows,
        [label for _, label in theme.APPEARANCE_CHOICES],
        [key for key, _ in theme.APPEARANCE_CHOICES].index(prefs.appearance),
        change_appearance,
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
            partial(choose_minutes, key, choices),
        ).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
    make_label(screen, "「5分だけやる」はいつでも5分です。", size=10, color=C.muted).pack(anchor="w", pady=(2, 0))

    make_label(screen, "終わったときの知らせ方", bold=True).pack(anchor="w", pady=(18, 4))
    for text, key in [
        ("音を鳴らす", "notify_sound"),
        ("ウィンドウを前面に出す", "notify_front"),
        ("OS の通知を出す（画面の隅にお知らせが表示されます）", "notify_os"),
    ]:
        make_checkbox(screen, text, getattr(prefs, key), partial(toggle, key)).pack(anchor="w")

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
            "このビルドでは配信サービスが設定されていません。\n"
            "（開発者向け: README の「週次レポート配信サービス」を参照）",
            size=10,
            color=C.muted,
            wraplength=app.px(TEXT_WIDTH),
            justify="left",
        ).pack(anchor="w")
        return

    settings = config.load_config()
    if settings.get("report_token"):
        registered = tk.Frame(frame, bg=frame["bg"])
        registered.pack(fill="x")
        make_label(registered, f"登録中: {settings.get('report_email', '')}", size=11).pack(side="left")
        make_link(registered, "変更", lambda: change_email(app)).pack(side="left", padx=(8, 0))
        # 登録後は、選び直すとすぐサーバーに反映する
        status = make_label(frame, size=10, color=C.muted, wraplength=app.px(TEXT_WIDTH), justify="left")
        picker = SchedulePicker(app, frame, report_service.get_schedule(settings))
        picker.on_change = lambda: update_schedule(app, picker, status)
        picker.frame.pack(anchor="w", pady=(8, 0))
        status.pack(anchor="w")
        # 最初のレポートを待たずに、届くか・どんな内容かをその場で確かめられるようにする
        make_button(frame, "テストメールを送る", lambda: send_test_report(app, status)).pack(fill="x", pady=(8, 0))
        build_sync_section(app, frame)
        # 登録の解除・配信停止は押し間違えないよう、目立たない文字のボタンにする（押すと確認が出る）
        links = tk.Frame(frame, bg=frame["bg"])
        links.pack(fill="x", pady=(12, 0))
        make_link(links, "すべての PC で配信を停止", lambda: unregister(app)).pack(side="right")
        make_label(links, "・", size=10, color=C.border).pack(side="right", padx=4)
        make_link(links, "この PC の登録を解除", lambda: remove_this_pc(app)).pack(side="right")
        return

    make_label(
        frame,
        "登録すると、同じメールアドレスで登録したほかの PC と記録を同期できます。",
        size=10,
        color=C.muted,
        wraplength=app.px(TEXT_WIDTH),
        justify="left",
    ).pack(anchor="w", pady=(0, 8))
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


def build_sync_section(app: JustDoItApp, frame: tk.Frame) -> None:
    """ほかの PC との同期（起動時にも自動で行う。ここでは結果の表示と「今すぐ同期」）"""
    make_label(frame, "ほかの PC との同期", bold=True).pack(anchor="w", pady=(20, 2))
    status = make_label(
        frame, sync_status_text(app), size=10, color=C.muted, wraplength=app.px(TEXT_WIDTH), justify="left"
    )
    status.pack(anchor="w")

    def on_synced(result, error):
        if error:
            log_error(error)
            status.config(text=f"同期できませんでした。{error_message(error)}")
        else:
            # 届くタイミングをほかの PC で変えていた場合にも表示が合うよう、画面ごと作り直す
            show_settings(app)

    # 起動時・登録直後の同期が終わったときも、この画面にいればここに結果を出す
    app.sync_listeners.append(on_synced)

    def sync_now():
        if not app.syncing:
            status.config(text="同期しています…")
            app.sync_records()

    make_button(frame, "今すぐ同期", sync_now).pack(fill="x", pady=(6, 0))


def error_message(error: Exception) -> str:
    """画面に出すエラーの言葉（通信のエラーは、すでに利用者向けの言葉になっている）"""
    if isinstance(error, ReportServiceError):
        return str(error)
    if isinstance(error, OSError):  # 作業ログを書き換えられなかった
        return "作業ログを書き換えられませんでした。Excel などで開いている場合は、閉じてからもう一度お試しください。"
    return "予期しないエラーが起きました。"


def log_error(error: Exception) -> None:
    """エラーの技術的な内容を error.log に残す（画面には利用者向けの言葉だけを出すため）"""
    if isinstance(error, ReportServiceError):
        # 通信の失敗だけ技術的な内容がある（サーバーが返したエラーは、メッセージがそのまま説明になっている）
        detail = error.detail
    else:
        detail = f"{type(error).__name__}: {error}"
    if detail:
        config.append_error_log(detail)


def sync_status_text(app: JustDoItApp) -> str:
    if app.syncing:
        return "同期しています…"
    if not app.last_sync:
        return "同じメールアドレスで登録したほかの PC と、記録をそろえます。"
    synced_at, result = app.last_sync
    changes = []
    if result.added:
        changes.append(f"{result.added}件取り込み")
    if result.removed:
        changes.append(f"{result.removed}件削除")
    if result.pushed:
        changes.append(f"{len(result.pushed)}件送信")
    if result.schedule_updated:
        changes.append(f"届くタイミングを{report_service.format_schedule(*result.schedule_updated)}に更新")
    if result.email_updated:
        changes.append("メールアドレスを更新")
    detail = "・".join(changes) if changes else "変更なし"
    return f"最後に同期: {synced_at:%m/%d %H:%M}（{detail}）"


class SchedulePicker:
    """「届くタイミング [月曜 ▼] [9時 ▼]」の選択欄"""

    def __init__(self, app: JustDoItApp, parent: tk.Widget, schedule: tuple[int, int]):
        self.on_change: Callable[[], None] | None = None
        self.saved = schedule  # 最後にサーバーへ保存できたタイミング（失敗したら戻す）

        self.frame = tk.Frame(parent, bg=parent["bg"])
        make_label(self.frame, "届くタイミング", size=11).pack(side="left", padx=(0, 10))
        weekday, hour = schedule
        self.weekday = make_select(
            self.frame, [f"{name}曜" for name in report_service.WEEKDAY_NAMES], weekday, self._changed
        )
        self.hour = make_select(
            self.frame,
            [f"{hour}時" for hour in report_service.REPORT_HOURS],
            report_service.REPORT_HOURS.index(hour),
            self._changed,
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
            if error:
                log_error(error)
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
    def on_verified(result: dict) -> None:
        # サーバーに保存されたタイミングを使う（返ってこない古いサーバーなら、選んだタイミング）
        saved = (result.get("weekday", schedule[0]), result.get("hour", schedule[1]))
        finish_register(app, email, result["token"], saved)

    weekday, hour = schedule
    send_with_code(app, email, {"action": "verify", "email": email, "weekday": weekday, "hour": hour}, on_verified)


def send_with_code(app: JustDoItApp, email: str, payload: dict, on_success: Callable[[dict], None]) -> None:
    """email に届いた確認コードを入力してもらい、payload に付けて送る（打ち間違えたら、その場で入力し直せる）"""
    code = simpledialog.askstring(
        "確認コード",
        f"{email} に届いた6桁の確認コードを入力してください。\n（迷惑メールフォルダに届く場合があります）",
        parent=app.root,
    )
    if code is None:
        return

    def on_done(result, error):
        if error:
            messagebox.showerror("確認エラー", str(error), parent=app.root)
            if error.code == "invalid_code":
                send_with_code(app, email, payload, on_success)
            return
        on_success(result)

    call_service_async(app, {**payload, "code": code.strip()}, on_done)


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

    # 登録前の記録を送り（最初のレポートから中身が入るように）、
    # 同じアドレスで登録済みのほかの PC の記録があれば取り込む
    app.sync_records()

    messagebox.showinfo(
        "登録完了",
        f"登録が完了しました。\n{report_service.format_schedule(*schedule)}、1週間の振り返りレポートがメールで届きます。\n"
        "同じメールアドレスで登録したほかの PC とは、記録が自動で同期されます。",
        parent=app.root,
    )
    show_settings(app)


# ==========================================
# メールアドレスの変更（新しいアドレス → 確認コード → 変更完了）
# ==========================================
def change_email(app: JustDoItApp) -> None:
    """登録中のメールアドレスを変える（記録・届くタイミング・ほかの PC の登録はそのまま引き継ぐ）"""
    if app.busy:
        return
    current = config.load_config().get("report_email", "")
    new_email = simpledialog.askstring(
        "メールアドレスを変更",
        f"新しいメールアドレスを入力してください。\n（今のアドレス: {current}）\n\n"
        "記録・届くタイミング・ほかの PC の登録は、そのまま引き継がれます。",
        parent=app.root,
    )
    if new_email is None:
        return
    new_email = new_email.strip()
    if "@" not in new_email:
        messagebox.showwarning("入力エラー", "メールアドレスを入力してください。", parent=app.root)
        return
    if new_email.lower() == current.lower():
        messagebox.showinfo("メールアドレスを変更", "今と同じメールアドレスです。", parent=app.root)
        return
    token = config.load_config().get("report_token")

    def on_changed(result: dict) -> None:
        settings_data = config.load_config()
        settings_data["report_email"] = result.get("email", new_email)
        try:
            config.save_config(settings_data)
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)
            return
        messagebox.showinfo(
            "変更完了",
            f"メールアドレスを {settings_data['report_email']} に変更しました。\n"
            "次の週次レポートから、新しいアドレスに届きます。",
            parent=app.root,
        )
        show_settings(app)

    def on_sent(result, error):
        if error:
            messagebox.showerror("送信エラー", str(error), parent=app.root)
            return
        send_with_code(app, new_email, {"action": "change_email", "token": token, "email": new_email}, on_changed)

    # 新しいアドレスで受け取れることを、確認コードで確かめてから変える
    call_service_async(app, {"action": "register", "email": new_email}, on_sent)


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
# テストメール
# ==========================================
def send_test_report(app: JustDoItApp, status: tk.Label) -> None:
    """今の記録でレポートを1通すぐに送る（送信回数はサーバー側で制限している）"""
    if app.busy:
        return
    status.config(text="テストメールを送っています…")
    # 送信待ちの記録があれば送り始めておく（テストメールに、なるべく最新の記録が入るように）
    report_service.start_sync()

    def on_done(result, error):
        if error:
            status.config(text="")
            messagebox.showerror("送信エラー", str(error), parent=app.root)
            return
        email = config.load_config().get("report_email", "")
        status.config(text=f"{email} にテストメールを送りました（迷惑メールフォルダも確認してください）")

    call_service_async(
        app, {"action": "send_test_report", "token": config.load_config().get("report_token")}, on_done
    )


# ==========================================
# 配信停止
# ==========================================
def remove_this_pc(app: JustDoItApp) -> None:
    """この PC だけ登録を解除する（ほかの PC の同期・メール・サーバーの記録はそのまま）"""
    if app.busy or not messagebox.askyesno(
        "この PC の登録を解除",
        "この PC だけ、週次レポートと同期の登録を解除しますか？\n\n"
        "・同じメールアドレスで登録したほかの PC は、これまでどおり同期できます\n"
        "・週次レポートのメールも、これまでどおり届きます\n"
        "・この PC の記録は残ります",
        parent=app.root,
    ):
        return
    token = config.load_config().get("report_token")

    def work():
        # この PC でまだ送れていない記録を先に送る（ほかの PC から見えなくならないように）
        url = report_service.get_service_url()
        queue_path = config.get_report_queue_path()
        report_service.sync_queue(url, queue_path, wait=True)
        if report_service.load_queue(queue_path):
            raise ReportServiceError(
                "まだサーバーに送れていない記録があります。インターネットにつながっているときに、もう一度お試しください",
                "network",
            )
        return report_service.call_service(url, {"action": "remove_device", "token": token})

    def on_done(result, error):
        app.busy = False
        app.root.config(cursor="")
        if error:
            log_error(error)
        # すでにサーバー側で解除済み（unauthorized）なら、そのままアプリ側も解除する
        if error and getattr(error, "code", None) != "unauthorized":
            messagebox.showerror("解除できませんでした", str(error), parent=app.root)
            return
        try:
            report_service.clear_registration()
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)
            return
        show_settings(app)

    app.busy = True
    app.root.config(cursor="watch")
    app.run_in_background(work, on_done)


def unregister(app: JustDoItApp) -> None:
    """すべての PC で配信と同期を停止し、サーバーの記録を消す"""
    if not messagebox.askyesno(
        "すべての PC で配信を停止",
        "週次レポートの配信と、ほかの PC との同期を停止しますか？\n\n"
        "・同じメールアドレスで登録したすべての PC で、登録が解除されます\n"
        "・サーバーに預けている記録（最大400日分）は、すべて削除されます\n"
        "・それぞれの PC の記録は残ります\n\n"
        "この PC だけ使わなくなる場合は「この PC の登録を解除」を使ってください。",
        icon="warning",
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
