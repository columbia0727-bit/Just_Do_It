"""アプリの土台（ウィンドウ・画面の切り替え・記録の保存・通知）とメインメニュー"""

from collections.abc import Callable
from datetime import datetime
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser

from justdoit import config, focus, notify, report_service, sync, updates
from justdoit.records import (
    append_record_to_csv,
    format_hours_mins,
    goal_text,
    load_records,
    streak_days,
    today_minutes,
    week_minutes,
)
from justdoit.ui import dashboard, settings, theme, timer
from justdoit.ui.theme import C, make_back_button, make_button, make_label, make_link

logger = logging.getLogger(__name__)
MENU_SIZE = (320, 340)
WELCOME_SIZE = (360, 460)


class JustDoItApp:
    """ウィンドウを管理し、画面の切り替えと記録の保存・通知を受け持つ

    各画面（timer / settings / dashboard / history）は、このクラスのインスタンスを受け取る関数として書く。
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        # 画面の中央に置くまでは隠しておく（OS が決めた位置に一瞬表示されないように）
        self.root.withdraw()
        self.root.title(config.APP_NAME)
        # ウィンドウ左上・タスクバーのアイコン（画像がなくてもアプリは動かす）
        try:
            self.icon = tk.PhotoImage(file=config.get_icon_path())
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        # 閉じるボタンが押されたら、タイマーや入力の途中か確認してから閉じる
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        # 画面の処理で予期しないエラーが起きたら、黙って画面が欠けるのではなく、知らせて記録を残す
        self.root.report_callback_exception = self.report_error

        # Windows の表示倍率（125%・150% など）。画面サイズや余白をこの倍率で広げる
        # （Mac は OS が拡大するので 1 のまま）
        self.scale = self.root.winfo_fpixels("1i") / 96 if sys.platform == "win32" else 1.0
        theme.set_scale(self.scale)
        # タイマーなどで予約した after 処理（画面を切り替えるときに取り消す）
        self.after_id: str | None = None
        # 今の画面だけで有効なキー操作（画面を切り替えるときに解除する）
        self.key_bindings: list[str] = []
        # 閉じる前に確認が必要な画面が設定する。False を返すと閉じるのをやめる
        self.close_guard: Callable[[], bool] | None = None
        # 配信サービスと通信中かどうか（通信中は設定画面から離れられないようにする）
        self.busy = False
        # 振り返り・設定で最後に選んだタブ（次に開いたときも同じタブで表示する）
        self.dashboard_period = "week"
        self.dashboard_offset = 0  # 振り返りで、直近から何期間前を見ているか
        self.settings_tab = "timer"
        # 記録一覧で最後に選んだ月（年, 月）。None ならいちばん新しい月
        self.history_month: tuple[int, int] | None = None
        # 今のウィンドウの大きさ（最初の画面は PC 画面の中央に置き、それ以降は今の中心を保って大きさを変える）
        self.window_size: tuple[int, int] | None = None
        # 新しいバージョンが出ていれば、そのリリース（起動時に別スレッドで確かめる）
        self.new_release: updates.Release | None = None
        # 今メインメニューを表示しているか（新しいバージョン・ほかの PC の記録が届いたら表示し直すため）
        self.on_menu = False
        # ほかの PC との同期（同期中か、最後に同期した時刻と結果）
        self.syncing = False
        self.last_sync: tuple[datetime, sync.SyncResult] | None = None
        # 同期が終わったら呼ぶ、今の画面の関数（設定画面が結果を表示するため。画面を切り替えると空にする）
        self.sync_listeners: list[Callable[[sync.SyncResult | None, Exception | None], None]] = []

        # 前回、記録する前にアプリや PC が終了したタイマーがあれば、まず記録できるようにする
        unsaved = focus.load_unsaved(config.get_unsaved_timer_path())
        if unsaved and not unsaved.worth_asking():
            focus.clear_unsaved(config.get_unsaved_timer_path())
            unsaved = None
        if unsaved:
            timer.show_unsaved_record(self, unsaved)
        elif is_first_launch():
            self.show_welcome()
        else:
            self.show_main_menu()
        self.root.deiconify()
        # 前回送れなかった記録を送り、ほかの PC の記録を取り込む
        if report_service.is_registered():
            self.sync_records()
        self.start_update_check()

    def run_in_background(self, work: Callable[[], object], on_done: Callable[[object, Exception | None], None]):
        """時間のかかる処理（通信）を別スレッドで行い、終わったら on_done(結果, エラー) を画面のスレッドで呼ぶ"""
        results: queue.SimpleQueue = queue.SimpleQueue()

        def worker():
            try:
                results.put((work(), None))
            except Exception as error:  # どんなエラーも、画面のスレッドで on_done に渡して扱う
                results.put((None, error))

        # Tk は別スレッドから触れないため、結果はキュー経由で受け取る
        # （画面を切り替えても止まらないよう、schedule ではなく root.after を使う）
        def wait_result():
            try:
                result, error = results.get_nowait()
            except queue.Empty:
                self.root.after(200, wait_result)
                return
            on_done(result, error)

        threading.Thread(target=worker, daemon=True).start()
        wait_result()

    def start_update_check(self) -> None:
        """新しいバージョンが出ているかを別スレッドで確かめ、見つかればメニューに知らせを出す"""

        def on_done(release, error):
            self.new_release = release
            if release and self.on_menu:
                self.show_main_menu()

        self.run_in_background(updates.check_for_update, on_done)

    def sync_records(self) -> None:
        """ほかの PC と記録を同期する（通信は別スレッド、手元の記録の書き換えは画面のスレッドで行う）

        結果は sync_listeners に登録した今の画面の関数に知らせる。
        """
        if self.syncing:
            return
        self.syncing = True

        def finished(state, error):
            self.syncing = False
            result = None
            if error is None:
                try:
                    result = sync.apply(state)
                    self.last_sync = (datetime.now(), result)
                except OSError as e:  # 作業ログを Excel で開いているなど
                    error = e
            elif getattr(error, "code", None) == "unauthorized":
                # メールのリンクなどから配信停止されていた
                report_service.clear_registration()
            if error:
                # つながらないだけ（オフライン）なら、次に起動したときにまた同期するので error.log には残さない
                offline = getattr(error, "code", None) in ("network", "busy")
                logger.log(logging.INFO if offline else logging.WARNING, "同期できませんでした: %s", error)
            # ほかの PC の記録・週の目標が届いたら、メニューの「今日の合計」「週の目標」を表示し直す
            if result and (result.changed or result.goal_updated is not None) and self.on_menu:
                self.show_main_menu()
            for listener in list(self.sync_listeners):
                listener(result, error)

        self.run_in_background(sync.fetch_server_state, finished)

    # ---------- 画面の土台 ----------
    def px(self, value: float) -> int:
        """100% 表示のときのピクセル数を、今の表示倍率に合わせて変換する"""
        return round(value * self.scale)

    def make_screen(self, size: tuple[int, int] = MENU_SIZE) -> tk.Frame:
        """前の画面を消して、余白付きの新しい画面の土台を返す"""
        self.cancel_scheduled()
        for sequence in self.key_bindings:
            self.root.unbind(sequence)
        self.key_bindings = []
        self.close_guard = None
        self.on_menu = False
        self.sync_listeners = []
        # タイマーが残り時間を出していたタイトルを元に戻す
        self.root.title(config.APP_NAME)
        for widget in self.root.winfo_children():
            widget.destroy()
        # 「デバイスに合わせる」のときは、画面を切り替えるたびに OS の設定を確かめて色を合わせる
        theme.apply_theme(self.root, config.load_preferences().appearance)
        self.resize_window(*size)
        screen = tk.Frame(self.root, bg=C.bg, padx=self.px(24), pady=self.px(20))
        screen.pack(fill="both", expand=True)
        return screen

    def make_header(
        self, screen: tk.Frame, title: str, back: Callable[[], None] | None = None
    ) -> tk.Frame:
        """タイトルと「戻る」を並べた見出し（Esc キーでも戻れる）。戻り先は back（省略時はメニュー）"""
        header = tk.Frame(screen, bg=C.bg)
        header.pack(fill="x", pady=(0, 16))
        make_label(header, title, size=16, bold=True).pack(side="left")

        def go_back():
            # 通信中に画面を離れると、結果のダイアログが別の画面（タイマー中など）に出てしまうため戻れなくする
            if not self.busy:
                (back or self.show_main_menu)()

        make_back_button(header, go_back).pack(side="right")
        self.bind_key("<Escape>", go_back)
        return header

    def bind_key(self, sequence: str, callback: Callable[[], None]) -> None:
        """今の画面だけで有効なキー操作を登録する"""
        self.root.bind(sequence, lambda event: callback())
        self.key_bindings.append(sequence)

    def resize_window(self, width: int, height: int) -> None:
        """ウィンドウの中心を保ったままサイズを変える（大きい画面が右下に寄らないように）

        起動直後はPC画面の中央に置く。はみ出す場合はPC画面内に収まるよう位置を寄せる。
        """
        width, height = self.px(width), self.px(height)
        # 同じ大きさなら何もしない（設定のタブの切り替えなど。余計な描き直しで画面がちらつかないように）
        if self.window_size == (width, height):
            return
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        # 「表示されているか」では判定しない（配色の切り替えでウィンドウが先に表示されることがあるため）
        if self.window_size:
            # ここで update_idletasks() を呼ぶと、作りかけの画面が先に描かれて表示がちぐはぐになるため、
            # 大きさは自分で覚えておいた値を使う（位置は利用者が動かすので、Tk から読む）
            old_width, old_height = self.window_size
            center_x = self.root.winfo_x() + old_width // 2
            center_y = self.root.winfo_y() + old_height // 2
        else:
            center_x, center_y = screen_width // 2, screen_height // 2

        x = max(0, min(center_x - width // 2, screen_width - width))
        y = max(0, min(center_y - height // 2, screen_height - height))
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.window_size = (width, height)

    def bring_to_front(self, on_top: bool) -> None:
        """ウィンドウを最前面に出す / 解除する"""
        self.root.attributes("-topmost", on_top)
        if on_top:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def report_error(self, exc_type, exc_value, exc_traceback) -> None:
        """予期しないエラーの内容を log/error.log に追記し、利用者に知らせる

        配布版は画面だけのアプリで、エラーの内容がどこにも表示されないため、原因を調べられるようにファイルに残す。
        """
        logger.error("予期しないエラーが起きました", exc_info=(exc_type, exc_value, exc_traceback))
        log_path = config.get_error_log_path()
        messagebox.showerror(
            "エラー",
            f"予期しないエラーが起きました。\n\n詳しい内容を次のファイルに保存しました:\n{log_path}",
            parent=self.root,
        )

    def on_close(self) -> None:
        if self.close_guard and not self.close_guard():
            return
        self.root.destroy()

    # ---------- after 処理の予約 ----------
    def schedule(self, delay_ms: int, callback: Callable[[], None]) -> None:
        """delay_ms 後に callback を呼ぶ（画面を切り替えると自動で取り消される）"""
        self.after_id = self.root.after(delay_ms, callback)

    def cancel_scheduled(self) -> None:
        """予約済みの after 処理を取り消す（画面遷移後にタイマーが動き続けるのを防ぐ）"""
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    # ---------- 通知 ----------
    def notify(self, title: str, message: str, prefs: config.Preferences | None = None) -> None:
        """タイマーの終わりを、設定画面で選んだ方法で知らせる"""
        prefs = prefs or config.load_preferences()
        if prefs.notify_sound and not notify.play_sound():
            self.root.bell()
        if prefs.notify_os:
            notify.show_notification(title, message)
        if prefs.notify_front:
            self.bring_to_front(True)

    # ---------- 記録の保存 ----------
    def save_record(self, task: str, duration_mins: int, recorded_at: datetime | None = None) -> bool:
        """ローカルCSVへの保存 ＆ 週次レポート用の送信。保存できたら True を返す

        recorded_at を省略すると今の日時で記録する（手動記録では、選んだ日時を渡す）。
        """
        now_str = (recorded_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

        try:
            append_record_to_csv(config.get_csv_path(), now_str, task, duration_mins)
        except OSError as e:
            messagebox.showerror(
                "保存エラー",
                f"作業ログを保存できませんでした:\n{e}\n\n"
                "作業ログを Excel などで開いている場合は、閉じてからもう一度保存してください。",
                parent=self.root,
            )
            return False
        logger.info("記録しました: %s %s（%d分）", now_str, task, duration_mins)

        # 週次レポートに登録済みなら、送信待ちキューに積んでから別スレッドで送る
        if report_service.is_registered():
            try:
                report_service.enqueue_logs(
                    config.get_report_queue_path(), [report_service.make_log(now_str, task, duration_mins)]
                )
            except OSError as e:
                logger.warning("週次レポート用の記録を保存できませんでした: %s", e)
            report_service.start_sync()
        return True

    # ---------- メインメニュー ----------
    def show_main_menu(self) -> None:
        """起動時のメインメニュー（迷わないよう、目立つボタンは「5分だけやる」の1つだけ）"""
        screen = self.make_screen(MENU_SIZE)
        focus_minutes = config.load_preferences().focus_minutes

        def start_short():
            timer.show_focus_timer(self, timer.FOCUS_SHORT_SECONDS)

        def start_long():
            timer.show_focus_timer(self, focus_minutes * 60)

        make_label(screen, "さあ、どうする？", size=16, bold=True).pack(pady=(20, 2))
        goal = week_goal_summary()
        make_label(screen, today_summary(), size=10, color=C.muted).pack(pady=(0, 0 if goal else 18))
        # 週の目標を決めていれば、今週の進み具合も出す
        if goal:
            make_label(screen, goal, size=10, color=C.accent).pack(pady=(0, 14))
        make_button(screen, "5分だけやる", start_short, primary=True).pack(fill="x", pady=4)
        make_button(screen, f"{focus_minutes}分やる", start_long).pack(fill="x", pady=4)
        # 表示はしないが、Enter キーでも「5分だけやる」を始められる
        self.bind_key("<Return>", start_short)

        links = tk.Frame(screen, bg=C.bg)
        links.pack(side="bottom")
        menu = [
            ("記録する", lambda: timer.show_manual_record(self)),
            ("振り返り", lambda: dashboard.show_dashboard(self)),
            ("設定", lambda: settings.show_settings(self)),
        ]
        for i, (text, command) in enumerate(menu):
            if i:
                make_label(links, "・", size=10, color=C.border).pack(side="left", padx=4)
            make_link(links, text, command).pack(side="left")

        # 新しいバージョンがあるときだけ、ダウンロードページへの案内を出す（メニューをシンプルに保つため）
        if self.new_release:
            release = self.new_release
            make_link(
                screen,
                f"新しいバージョン {release.version} があります",
                lambda: webbrowser.open(release.url),
                accent=True,
            ).pack(side="bottom", pady=(0, 10))
        self.on_menu = True

    # ---------- 初めて起動したときの案内 ----------
    def show_welcome(self) -> None:
        """使い方を3ステップで示し、そのまま「5分だけやる」を始められるようにする（初回だけ）"""
        screen = self.make_screen(WELCOME_SIZE)
        mark_welcomed()

        make_label(screen, "ようこそ", size=18, bold=True).pack(pady=(12, 2))
        make_label(screen, "やる気が出ないときこそ、まずは5分だけ。", size=11, color=C.muted).pack(pady=(0, 18))
        steps = tk.Frame(screen, bg=C.bg)
        steps.pack(fill="x")
        for number, (title, detail) in enumerate(
            [
                ("5分だけやる", "タイマーで5分だけ集中。乗ってきたら、そのまま続けられます"),
                ("一言で記録", "終わったら、やったことを一言入力して記録"),
                ("振り返る", "記録はグラフで振り返れます。設定から、週次レポートのメールも受け取れます"),
            ],
            start=1,
        ):
            row = tk.Frame(steps, bg=C.bg)
            row.pack(fill="x", pady=(0, 12))
            make_label(row, str(number), size=14, bold=True, color=C.accent, width=2, anchor="w").pack(
                side="left", anchor="n", padx=(0, 4)
            )
            text = tk.Frame(row, bg=C.bg)
            text.pack(side="left", fill="x")
            make_label(text, title, size=12, bold=True).pack(anchor="w")
            make_label(text, detail, size=10, color=C.muted, wraplength=self.px(250), justify="left").pack(anchor="w")

        def start_now():
            timer.show_focus_timer(self, timer.FOCUS_SHORT_SECONDS)

        actions = tk.Frame(screen, bg=C.bg)
        actions.pack(side="bottom", fill="x")
        make_button(actions, "5分だけやってみる", start_now, primary=True).pack(fill="x")
        make_link(actions, "メニューを見る", self.show_main_menu).pack(pady=(10, 0))
        self.bind_key("<Return>", start_now)


def is_first_launch() -> bool:
    """初めて起動したか（案内をまだ見ておらず、記録も無い。以前のバージョンから更新した人には出さない）"""
    if config.load_config().get("welcomed"):
        return False
    try:
        return load_records(config.get_csv_path()).empty
    except (OSError, ValueError):
        return False


def mark_welcomed() -> None:
    settings_data = config.load_config()
    settings_data["welcomed"] = True
    try:
        config.save_config(settings_data)
    except OSError:
        pass  # 保存できなくても、次に起動したときにもう一度案内が出るだけ


def today_summary() -> str:
    """メニューに出す「今日 50分 ・ 3日連続」（作業ログが読めなければ空）"""
    try:
        records = load_records(config.get_csv_path())
    except (OSError, ValueError):
        return ""
    text = f"今日 {format_hours_mins(today_minutes(records))}"
    streak = streak_days(records)
    if streak >= 2:
        text += f" ・ {streak}日連続"
    return text


def week_goal_summary() -> str:
    """メニューに出す「今週 1時間 20分 / 目標 3時間」（目標なし・作業ログが読めなければ空）"""
    goal = config.load_preferences().weekly_goal_minutes
    if not goal:
        return ""
    try:
        records = load_records(config.get_csv_path())
    except (OSError, ValueError):
        return ""
    return goal_text(goal, week_minutes(records))


def run() -> None:
    """アプリを起動する"""
    # sys.platform で分ける（mypy が OS ごとに見分け、Windows にしかない ctypes.windll をエラーにしないように）
    if sys.platform == "win32":
        # python.exe とは別のアプリとして扱わせ、タスクバーに Python ではなくアプリのアイコンを出す
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JustDoIt.App")
        # 表示倍率が 100% 以外の PC で文字がぼやけないよう、Windows による拡大をやめて自前で拡大する
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    config.setup_logging()
    # 以前のバージョンが config.json に保存した週次レポートのトークンを、資格情報マネージャーに移す
    config.migrate_report_token()
    root = tk.Tk()
    JustDoItApp(root)
    root.mainloop()
