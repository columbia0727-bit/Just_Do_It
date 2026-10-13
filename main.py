import csv
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import platform
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
import urllib.request

# ダッシュボード（データ分析・可視化）用のライブラリ
# pyplot を使わず Figure を直接生成することで、Tkinter 埋め込み時のメモリリークを防ぐ
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

APP_NAME = "Just do it."
APP_DIR_NAME = "JustDoIt"

FOCUS_SHORT_SECONDS = 5 * 60
FOCUS_LONG_SECONDS = 25 * 60
BREAK_SECONDS = 10 * 60
MAX_MANUAL_MINUTES = 24 * 60
GAS_TIMEOUT_SECONDS = 10
# 振り返りの期間: キー → (切り替えボタンの表示, 日数, 見出し)
DASHBOARD_PERIODS = {
    "week": ("週", 7, "直近7日"),
    "month": ("月", 30, "直近30日"),
    "year": ("年", 365, "直近12か月"),
}

# 週次レポート配信サービス（開発者がデプロイした gas/report_service/ の WebアプリURL）
# 環境変数 JUSTDOIT_REPORT_URL が設定されていればそちらを優先する
REPORT_SERVICE_URL = "https://script.google.com/macros/s/AKfycbwsGmQMb4egG6jISjSEh1KR3QIEDJ-AxTSdWUhMFVB9GWOn2f1WZEg6koFYFOS8_jutpQ/exec"
# 登録直後のレポートが空にならないよう、登録時に送る過去の記録の日数
REPORT_BACKFILL_DAYS = 14

MENU_GEOMETRY = "320x340"

# 画面の配色（作業の邪魔をしないよう、色はアクセント1色に絞る）
COLOR_BG = "#f7f7f5"
COLOR_TEXT = "#222222"
COLOR_MUTED = "#8a8a86"
COLOR_BORDER = "#dcdcd8"
COLOR_SUBTLE = "#ebebe7"
COLOR_SUBTLE_HOVER = "#e0e0db"
COLOR_ACCENT = "#2f6f62"
COLOR_ACCENT_HOVER = "#265a50"
COLOR_ERROR = "#b3261e"

# OSに合わせて日本語フォントを切り替える（画面とグラフの両方）
if platform.system() == "Darwin":  # Macの場合
    UI_FONT_FAMILY = "Hiragino Sans"
    rcParams["font.sans-serif"] = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Arial"]
elif platform.system() == "Windows":  # Windowsの場合
    UI_FONT_FAMILY = "Yu Gothic UI"
    rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "MS Gothic", "Arial"]
else:  # Linux等の場合
    UI_FONT_FAMILY = "Noto Sans CJK JP"
    rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


# ==========================================
# 保存先・設定まわり
# ==========================================
def get_icon_path():
    """アプリアイコンの画像（PyInstaller でビルドした場合は同梱したファイル）"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "icon.png"


def get_data_dir():
    """作業ログと設定ファイルの保存先ディレクトリを返す

    ソースから実行した場合は main.py と同じフォルダ、
    PyInstaller でビルドしたアプリの場合は OS 標準のユーザーデータフォルダを使う
    （.exe / .app の中には書き込めないため）。
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent

    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


def get_csv_path():
    return get_data_dir() / "log" / "work_log.csv"


def get_config_path():
    return get_data_dir() / "config.json"


def load_config():
    """config.json を読み込む（存在しない・壊れている場合は空の設定）"""
    try:
        with open(get_config_path(), encoding="utf-8") as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config):
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_report_service_url():
    return os.environ.get("JUSTDOIT_REPORT_URL") or REPORT_SERVICE_URL


def get_report_queue_path():
    return get_data_dir() / "log" / "report_queue.json"


def is_report_registered():
    return bool(get_report_service_url() and load_config().get("report_token"))


# ==========================================
# 記録の保存・送信
# ==========================================
def append_record_to_csv(csv_path, now_str, task, duration_mins):
    """ローカルCSVに1行追記する(newline=""で空行を防止、utf-8-sigでExcel互換)"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([now_str, task, f"{duration_mins}分"])


def post_json(url, payload):
    """JSON を POST し、レスポンスの JSON を dict で返す"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=GAS_TIMEOUT_SECONDS) as res:
        return json.loads(res.read().decode("utf-8"))


# ==========================================
# 週次レポート配信サービスとの通信
# ==========================================
class ReportServiceError(Exception):
    """配信サービスのエラー。code は "network"（通信失敗）や "unauthorized"（トークン無効）など"""

    def __init__(self, message, code="error"):
        super().__init__(message)
        self.code = code


def call_report_service(url, payload):
    """配信サービスを呼び出して結果の dict を返す。失敗時は ReportServiceError を送出"""
    try:
        result = post_json(url, payload)
    except (OSError, ValueError) as e:
        raise ReportServiceError(f"サーバーに接続できませんでした: {e}", "network") from e
    if result.get("status") != "success":
        raise ReportServiceError(result.get("message", "不明なエラー"), result.get("code", "error"))
    return result


# 送信待ちキューは UI スレッド（追加）と送信スレッド（削除）の両方から触るためロックで守る
_report_queue_lock = threading.Lock()
# 送信スレッドが同時に複数動かないようにする
_report_sync_lock = threading.Lock()


def load_report_queue(queue_path):
    try:
        with open(queue_path, encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_report_queue(queue_path, items):
    # 書き込み途中でアプリが終了してもファイルが壊れないよう、一時ファイルから置き換える
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = queue_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, queue_path)


def enqueue_report_logs(queue_path, logs):
    with _report_queue_lock:
        save_report_queue(queue_path, load_report_queue(queue_path) + list(logs))


def clear_report_registration():
    """保存済みのトークンと送信待ちの記録を削除する"""
    config = load_config()
    config.pop("report_token", None)
    config.pop("report_email", None)
    save_config(config)
    with _report_queue_lock:
        save_report_queue(get_report_queue_path(), [])


def sync_report_queue(url, queue_path):
    """送信待ちの記録を配信サービスへ順に送る（別スレッドから呼ぶ）

    通信できなかった分はキューに残して次回（次の記録時・次回起動時）に再送する。
    トークンが無効になっていた場合（メールのリンクから配信停止された等）は登録を解除する。
    """
    if not _report_sync_lock.acquire(blocking=False):
        return
    try:
        while True:
            token = load_config().get("report_token")
            with _report_queue_lock:
                pending = load_report_queue(queue_path)
            if not token or not pending:
                return

            processed = 0
            stop = False
            for log in pending:
                try:
                    call_report_service(url, {"action": "log", "token": token, **log})
                except ReportServiceError as e:
                    if e.code == "network" or e.code == "busy":
                        print(f"⚠️ 週次レポート用の記録を送信できませんでした（次回再送）: {e}")
                        stop = True
                        break
                    if e.code == "unauthorized":
                        print("⚠️ 週次レポートの登録が解除されていました")
                        clear_report_registration()
                        return
                    # 形式エラーなど再送しても成功しない記録は捨てる
                    print(f"⚠️ 週次レポート用の記録を送信できませんでした（破棄）: {e}")
                processed += 1

            # 送信中に追加された記録はキューの末尾にあるので、先頭から送信済みの分だけ取り除く
            with _report_queue_lock:
                save_report_queue(queue_path, load_report_queue(queue_path)[processed:])
            if stop or processed == 0:
                return
    finally:
        _report_sync_lock.release()


def build_backfill_logs(records, days=REPORT_BACKFILL_DAYS, now=None):
    """作業ログの DataFrame から、直近 days 日分を配信サービスへ送る形式に変換する"""
    start = (now or datetime.now()) - timedelta(days=days)
    recent = records[(records["日時"] >= start) & (records["分"] > 0)]
    return [
        {"datetime": row.日時.strftime("%Y-%m-%d %H:%M:%S"), "task": row.作業内容, "minutes": int(row.分)}
        for row in recent.itertuples(index=False)
    ]


# ==========================================
# 集計（ダッシュボード用）
# ==========================================
def parse_minutes(value):
    """「25分」「25」などの文字列から分数(int)を取り出す。取り出せなければ0"""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else 0


def load_records(csv_path):
    """作業ログCSVを [日時, 作業内容, 分] の DataFrame として読み込む"""
    df = pd.read_csv(
        csv_path,
        encoding="utf-8-sig",
        header=None,
        engine="python",
        on_bad_lines="skip",
    )
    if df.shape[1] < 3:
        raise ValueError(
            "CSVのデータ構造が正しくありません。[日時, 作業内容, 実施時間] の形式か確認してください。"
        )

    records = pd.DataFrame(
        {
            "日時": pd.to_datetime(df.iloc[:, 0], format="%Y-%m-%d %H:%M:%S", errors="coerce"),
            "作業内容": df.iloc[:, 1].astype(str).str.strip(),
            "分": df.iloc[:, 2].map(parse_minutes),
        }
    )
    return records.dropna(subset=["日時"])


def summarize_by_task(records):
    summary = records.groupby("作業内容")["分"].sum()
    return summary[summary > 0].sort_values(ascending=False)


def summarize_by_day(records, days=7, today=None):
    """直近 days 日分の日別合計（記録がない日も0分として含める）"""
    today = (today or datetime.now()).date()
    index = pd.date_range(today - timedelta(days=days - 1), today).date
    daily = records.groupby(records["日時"].dt.date)["分"].sum()
    return daily.reindex(index, fill_value=0)


def summarize_period(records, period, today=None):
    """振り返りの期間（"week" / "month" / "year"）ごとの集計

    week は直近7日・month は直近30日を日別（分）で、year は直近12か月を月別（時間）で返す。
    """
    today = (today or datetime.now()).date()
    if period == "year":
        months = pd.period_range(end=pd.Period(today, freq="M"), periods=12, freq="M")
        start = months[0].start_time.date()
    else:
        start = today - timedelta(days=DASHBOARD_PERIODS[period][1] - 1)

    dates = records["日時"].dt.date
    in_range = records[(dates >= start) & (dates <= today)]
    daily = summarize_by_day(in_range, days=(today - start).days + 1, today=datetime.combine(today, datetime.min.time()))

    if period == "year":
        monthly = in_range.groupby(in_range["日時"].dt.to_period("M"))["分"].sum().reindex(months, fill_value=0)
        labels = [f"{p.month}月" for p in months]
        values = [round(mins / 60, 1) for mins in monthly.values]
        unit = "時間"
    else:
        labels = [f"{d.month}/{d.day}" for d in daily.index]
        values = [int(mins) for mins in daily.values]
        unit = "分"

    return {
        "title": DASHBOARD_PERIODS[period][2],
        "labels": labels,
        "values": values,
        "unit": unit,
        "total": int(in_range["分"].sum()),
        "active_days": int((daily > 0).sum()),
        "span_days": len(daily),
        "by_task": summarize_by_task(in_range),
    }


def format_hours_mins(total_mins):
    """「1時間 20分」の形にする（1時間未満は「41分」、ちょうどの時間は「2時間」）"""
    hours, mins = divmod(int(total_mins), 60)
    if hours == 0:
        return f"{mins}分"
    return f"{hours}時間" if mins == 0 else f"{hours}時間 {mins}分"


# ==========================================
# GUI
# ==========================================
def ui_font(size=12, bold=False):
    return (UI_FONT_FAMILY, size, "bold") if bold else (UI_FONT_FAMILY, size)


def make_label(parent, text="", size=12, color=COLOR_TEXT, bold=False, **options):
    return tk.Label(parent, text=text, font=ui_font(size, bold), fg=color, bg=parent["bg"], **options)


def make_button(parent, text, command, primary=False):
    """平らなボタン（tk.Button は Mac で背景色が反映されないため Label で作る）"""
    if primary:
        bg, hover_bg, fg = COLOR_ACCENT, COLOR_ACCENT_HOVER, "white"
    else:
        bg, hover_bg, fg = COLOR_SUBTLE, COLOR_SUBTLE_HOVER, COLOR_TEXT
    button = tk.Label(
        parent, text=text, font=ui_font(12, bold=primary), fg=fg, bg=bg, pady=9, cursor="hand2"
    )
    button.bind("<Button-1>", lambda event: command())
    button.bind("<Enter>", lambda event: button.config(bg=hover_bg))
    button.bind("<Leave>", lambda event: button.config(bg=bg))
    return button


def make_link(parent, text, command):
    """目立たせたくない操作用の、文字だけのボタン"""
    link = make_label(parent, text, size=10, color=COLOR_MUTED, cursor="hand2")
    link.bind("<Button-1>", lambda event: command())
    link.bind("<Enter>", lambda event: link.config(fg=COLOR_TEXT))
    link.bind("<Leave>", lambda event: link.config(fg=COLOR_MUTED))
    return link


def make_entry(parent, **options):
    return tk.Entry(
        parent,
        font=ui_font(12),
        relief="flat",
        bg="white",
        fg=COLOR_TEXT,
        insertbackground=COLOR_TEXT,
        highlightthickness=1,
        highlightbackground=COLOR_BORDER,
        highlightcolor=COLOR_ACCENT,
        **options,
    )


def format_clock(seconds):
    mins, secs = divmod(seconds, 60)
    return f"{mins:02d}:{secs:02d}"


class JustDoItApp:

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.configure(bg=COLOR_BG)
        # ウィンドウ左上・タスクバーのアイコン（画像がなくてもアプリは動かす）
        try:
            self.icon = tk.PhotoImage(file=get_icon_path())
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self.after_id = None
        self.running = False
        # Windows の表示倍率（125%・150% など）。画面サイズや余白をこの倍率で広げる
        # （Mac は OS が拡大するので 1 のまま）
        self.scale = self.root.winfo_fpixels("1i") / 96 if platform.system() == "Windows" else 1.0

        self.create_main_menu()
        # 前回送れなかった記録があれば再送する
        self.start_report_sync()

    def clear_window(self):
        """画面上のウィジェットをすべてクリアし、動いているタイマーも止める"""
        self.cancel_timer()
        for widget in self.root.winfo_children():
            widget.destroy()

    def cancel_timer(self):
        """予約済みの after 処理を取り消す（画面遷移後にタイマーが動き続けるのを防ぐ）"""
        self.running = False
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def bring_to_front(self, on_top):
        """ウィンドウを最前面に出す / 解除する"""
        self.root.attributes("-topmost", on_top)
        if on_top:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def px(self, value):
        """100% 表示のときのピクセル数を、今の表示倍率に合わせて変換する"""
        return round(value * self.scale)

    def resize_window(self, width, height):
        """ウィンドウの中心を保ったままサイズを変える（大きい画面が右下に寄らないように）

        起動直後はPC画面の中央に置く。はみ出す場合はPC画面内に収まるよう位置を寄せる。
        """
        width, height = self.px(width), self.px(height)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        if self.root.winfo_ismapped():
            self.root.update_idletasks()
            center_x = self.root.winfo_x() + self.root.winfo_width() // 2
            center_y = self.root.winfo_y() + self.root.winfo_height() // 2
        else:
            center_x, center_y = screen_width // 2, screen_height // 2

        x = max(0, min(center_x - width // 2, screen_width - width))
        y = max(0, min(center_y - height // 2, screen_height - height))
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def make_screen(self, geometry=MENU_GEOMETRY):
        """前の画面を消して、余白付きの新しい画面の土台を返す"""
        self.clear_window()
        self.resize_window(*map(int, geometry.split("x")))
        screen = tk.Frame(self.root, bg=COLOR_BG, padx=self.px(24), pady=self.px(20))
        screen.pack(fill="both", expand=True)
        return screen

    def make_header(self, screen, title):
        """タイトルと「戻る」を並べた見出し"""
        header = tk.Frame(screen, bg=COLOR_BG)
        header.pack(fill="x", pady=(0, 16))
        make_label(header, title, size=16, bold=True).pack(side="left")
        make_link(header, "戻る", self.create_main_menu).pack(side="right")
        return header

    def make_tabs(self, parent, options, selected, on_select):
        """「週｜月｜年」のような切り替えボタン（選んでいるものだけ白く浮かせる）"""
        tabs = tk.Frame(parent, bg=COLOR_SUBTLE, padx=2, pady=2)
        for key, text in options:
            active = key == selected
            tab = tk.Label(
                tabs,
                text=text,
                font=ui_font(10, bold=active),
                fg=COLOR_TEXT if active else COLOR_MUTED,
                bg="white" if active else COLOR_SUBTLE,
                padx=self.px(14),
                pady=self.px(2),
                cursor="arrow" if active else "hand2",
            )
            tab.pack(side="left")
            if not active:
                tab.bind("<Button-1>", lambda event, k=key: on_select(k))
        return tabs

    def create_main_menu(self):
        """起動時のメインメニュー（迷わないよう、目立つボタンは「5分だけやる」の1つだけ）"""
        screen = self.make_screen(MENU_GEOMETRY)

        make_label(screen, "さあ、どうする？", size=16, bold=True).pack(pady=(28, 24))
        make_button(
            screen,
            "5分だけやる",
            lambda: self.start_timer(FOCUS_SHORT_SECONDS, "5分"),
            primary=True,
        ).pack(fill="x", pady=4)
        make_button(
            screen, "25分やる", lambda: self.start_timer(FOCUS_LONG_SECONDS, "25分")
        ).pack(fill="x", pady=4)

        links = tk.Frame(screen, bg=COLOR_BG)
        links.pack(side="bottom")
        for i, (text, command) in enumerate(
            [("記録する", self.manual_record_flow), ("振り返り", self.show_dashboard), ("設定", self.show_settings)]
        ):
            if i:
                make_label(links, "・", size=10, color=COLOR_BORDER).pack(side="left", padx=4)
            make_link(links, text, command).pack(side="left")

    # ---------- 集中タイマー ----------
    def start_timer(self, duration_seconds, timer_name):
        """タイマーを開始する処理"""
        screen = self.make_screen()
        self.target_seconds = duration_seconds
        self.start_time = datetime.now()
        self.running = True

        make_label(screen, f"集中（{timer_name}）", size=11, color=COLOR_MUTED).pack(pady=(24, 0))
        self.label = make_label(screen, format_clock(duration_seconds), size=44)
        self.label.pack()

        make_link(screen, "記録せずにやめる", self.create_main_menu).pack(side="bottom", pady=(10, 0))
        # 途中で終えても、そこまでの時間を記録できる
        make_button(screen, "ここで終える", self.abort_timer).pack(side="bottom", fill="x")

        self.check_time()

    def check_time(self):
        """1秒ごとに残り時間をチェックするループ処理"""
        if not self.running:
            return
        elapsed = datetime.now() - self.start_time
        remaining = self.target_seconds - int(elapsed.total_seconds())

        if remaining > 0:
            self.label.config(text=format_clock(remaining))
            self.after_id = self.root.after(1000, self.check_time)
        else:
            self.after_id = None
            self.time_up()

    def abort_timer(self):
        """「ここで終える」が押されたときの処理（経過時間を記録してメニューへ）"""
        self.cancel_timer()

        elapsed_secs = int((datetime.now() - self.start_time).total_seconds())
        # 1分未満で中断した場合でも最低「1分」として切り上げる
        duration_mins = max(1, (elapsed_secs + 59) // 60)
        self.ask_task("おつかれさまでした", duration_mins, after_save=self.create_main_menu)

    def time_up(self):
        """タイマー終了時の処理（音で知らせて前面に出し、そのまま記録画面へ）"""
        self.running = False
        self.root.bell()
        self.bring_to_front(True)
        self.ask_task(
            "おつかれさまでした",
            self.target_seconds // 60,
            after_save=self.start_break_timer,
            save_text="記録して休憩する",
        )

    def ask_task(self, heading, duration_mins, after_save, save_text="記録する"):
        """やったことを入力して記録する画面（タイマー終了時・途中終了時で共通）"""
        screen = self.make_screen()

        make_label(screen, heading, size=16, bold=True).pack(pady=(16, 0))
        make_label(screen, f"{duration_mins}分", size=11, color=COLOR_MUTED).pack()

        make_label(screen, "何をやった？", size=11).pack(anchor="w", pady=(20, 4))
        task_entry = make_entry(screen)
        task_entry.pack(fill="x", ipady=4)
        task_entry.focus_set()
        error_label = make_label(screen, size=10, color=COLOR_ERROR)
        error_label.pack(anchor="w")

        def save(event=None):
            task = task_entry.get().strip()
            if not task:
                error_label.config(text="やったことを入力してください")
                return
            self.bring_to_front(False)
            self.save_record(task, duration_mins)
            after_save()

        def skip():
            self.bring_to_front(False)
            self.create_main_menu()

        make_link(screen, "記録しない", skip).pack(side="bottom", pady=(10, 0))
        make_button(screen, save_text, save, primary=True).pack(side="bottom", fill="x")
        task_entry.bind("<Return>", save)

    # ---------- 休憩タイマー ----------
    def start_break_timer(self):
        """10分間の休憩タイマー処理"""
        screen = self.make_screen()
        self.break_start_time = datetime.now()
        self.running = True

        make_label(screen, "休憩", size=11, color=COLOR_MUTED).pack(pady=(24, 0))
        self.break_label = make_label(screen, format_clock(BREAK_SECONDS), size=44)
        self.break_label.pack()

        make_button(screen, "休憩を終える", self.create_main_menu).pack(side="bottom", fill="x")

        self.check_break_time()

    def check_break_time(self):
        """休憩時間のカウントダウン（終わったら音で知らせてメニューへ戻る）"""
        if not self.running:
            return
        elapsed = datetime.now() - self.break_start_time
        remaining = BREAK_SECONDS - int(elapsed.total_seconds())

        if remaining > 0:
            self.break_label.config(text=format_clock(remaining))
            self.after_id = self.root.after(1000, self.check_break_time)
        else:
            self.after_id = None
            self.running = False
            self.root.bell()
            self.bring_to_front(True)
            self.create_main_menu()
            self.bring_to_front(False)

    # ---------- 手動記録 ----------
    def manual_record_flow(self):
        """手動記録用の画面に切り替える"""
        screen = self.make_screen()
        self.make_header(screen, "記録する")

        make_label(screen, "やったこと", size=11).pack(anchor="w", pady=(0, 4))
        task_entry = make_entry(screen)
        task_entry.pack(fill="x", ipady=4)
        task_entry.focus_set()

        make_label(screen, "時間（分）", size=11).pack(anchor="w", pady=(12, 4))
        mins_entry = make_entry(screen, width=8)
        mins_entry.pack(anchor="w", ipady=4)

        error_label = make_label(screen, size=10, color=COLOR_ERROR)
        error_label.pack(anchor="w")

        def save_and_back(event=None):
            task = task_entry.get().strip()
            mins_str = mins_entry.get().strip()

            if not task:
                error_label.config(text="やったことを入力してください")
                task_entry.focus_set()
                return

            if not mins_str.isdigit() or not 1 <= int(mins_str) <= MAX_MANUAL_MINUTES:
                error_label.config(text=f"時間は 1〜{MAX_MANUAL_MINUTES} の数字で入力してください")
                mins_entry.focus_set()
                return

            self.save_record(task, int(mins_str))
            self.create_main_menu()

        make_button(screen, "記録する", save_and_back, primary=True).pack(side="bottom", fill="x")

        # Enterキーでの保存対応
        task_entry.bind("<Return>", lambda event: mins_entry.focus_set())
        mins_entry.bind("<Return>", save_and_back)

    # ---------- 保存 ----------
    def save_record(self, task, duration_mins):
        """ローカルCSVへの保存 ＆ 週次レポート用の送信"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            append_record_to_csv(get_csv_path(), now_str, task, duration_mins)
        except OSError as e:
            messagebox.showerror(
                "保存エラー", f"作業ログを保存できませんでした:\n{e}", parent=self.root
            )
            return
        print(f"【ローカル保存完了】{now_str} - {task} ({duration_mins}分)")

        # 週次レポートに登録済みなら、送信待ちキューに積んでから別スレッドで送る
        if is_report_registered():
            log = {"datetime": now_str, "task": task, "minutes": duration_mins}
            try:
                enqueue_report_logs(get_report_queue_path(), [log])
            except OSError as e:
                print(f"⚠️ 週次レポート用の記録を保存できませんでした: {e}")
            self.start_report_sync()

    def start_report_sync(self):
        url = get_report_service_url()
        if url and load_config().get("report_token"):
            threading.Thread(
                target=sync_report_queue, args=(url, get_report_queue_path()), daemon=True
            ).start()

    # ---------- 週次レポートの登録・解除 ----------
    def call_report_service_busy(self, payload):
        """配信サービスを呼び出す（数秒かかるので、その間はカーソルを待機表示にする）"""
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            return call_report_service(get_report_service_url(), payload)
        finally:
            self.root.config(cursor="")

    def register_report(self, email):
        email = email.strip()
        if "@" not in email:
            messagebox.showwarning(
                "入力エラー", "メールアドレスを入力してください。", parent=self.root
            )
            return

        try:
            self.call_report_service_busy({"action": "register", "email": email})
        except ReportServiceError as e:
            messagebox.showerror("送信エラー", str(e), parent=self.root)
            return

        # コードの打ち間違いは、その場で入力し直せるようにする
        while True:
            code = simpledialog.askstring(
                "確認コード",
                f"{email} に届いた6桁の確認コードを入力してください。\n"
                "（迷惑メールフォルダに届く場合があります）",
                parent=self.root,
            )
            if code is None:
                return
            try:
                result = self.call_report_service_busy(
                    {"action": "verify", "email": email, "code": code.strip()}
                )
                break
            except ReportServiceError as e:
                messagebox.showerror("確認エラー", str(e), parent=self.root)
                if e.code != "invalid_code":
                    return

        config = load_config()
        config["report_email"] = email
        config["report_token"] = result["token"]
        try:
            save_config(config)
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=self.root)
            return

        # 登録前の記録も送っておき、最初のレポートから中身が入るようにする
        csv_path = get_csv_path()
        if csv_path.exists():
            try:
                enqueue_report_logs(get_report_queue_path(), build_backfill_logs(load_records(csv_path)))
            except (OSError, ValueError) as e:
                print(f"⚠️ 過去の記録を送信できませんでした: {e}")
        self.start_report_sync()

        messagebox.showinfo(
            "登録完了",
            "登録が完了しました。\n毎週月曜 9時ごろ、先週の振り返りレポートがメールで届きます。",
            parent=self.root,
        )
        self.show_settings()

    def unregister_report(self):
        if not messagebox.askyesno(
            "配信停止",
            "週次レポートの配信を停止しますか？\nサーバーに保存された作業記録も削除されます（アプリ内の記録は残ります）。",
            parent=self.root,
        ):
            return

        try:
            self.call_report_service_busy(
                {"action": "unregister", "token": load_config().get("report_token")}
            )
        except ReportServiceError as e:
            # すでにサーバー側で解除済み（unauthorized）なら、そのままアプリ側も解除する
            if e.code != "unauthorized":
                messagebox.showerror(
                    "停止エラー",
                    f"{e}\n時間をおいて再度お試しいただくか、レポートメール内のリンクから停止してください。",
                    parent=self.root,
                )
                return

        try:
            clear_report_registration()
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=self.root)
            return
        self.show_settings()

    # ---------- 設定 ----------
    def show_settings(self):
        """週次レポートの登録画面"""
        screen = self.make_screen("460x360")
        self.make_header(screen, "設定")

        make_label(screen, "週次レポート", bold=True).pack(anchor="w")
        make_label(
            screen, "毎週月曜 9時ごろ、先週の振り返りがメールで届きます。", size=10, color=COLOR_MUTED
        ).pack(anchor="w", pady=(2, 8))
        self.build_report_settings(screen)

        make_label(
            screen,
            f"保存先: {get_data_dir()}",
            size=9,
            color=COLOR_MUTED,
            wraplength=self.px(410),
            justify="left",
        ).pack(side="bottom", anchor="w")

    def build_report_settings(self, frame):
        """設定画面の週次レポート欄（登録状態に応じて表示を切り替える）"""
        config = load_config()

        if not get_report_service_url():
            make_label(
                frame,
                "このビルドでは配信サービスが設定されていません。\n（開発者向け: README の「週次レポート配信サービス」を参照）",
                size=10,
                color=COLOR_MUTED,
                wraplength=self.px(410),
                justify="left",
            ).pack(anchor="w")
            return

        if config.get("report_token"):
            make_label(frame, f"登録中: {config.get('report_email', '')}", size=11).pack(anchor="w")
            make_button(frame, "配信を停止する", self.unregister_report).pack(fill="x", pady=(8, 0))
            return

        email_entry = make_entry(frame)
        email_entry.pack(fill="x", ipady=4)
        email_entry.focus_set()

        def register(event=None):
            self.register_report(email_entry.get())

        make_button(frame, "確認コードを送る", register, primary=True).pack(fill="x", pady=(8, 0))
        email_entry.bind("<Return>", register)

    # ---------- 振り返り（ダッシュボード） ----------
    def show_dashboard(self, period=None):
        """ローカルのCSVを読み込んで、期間（週・月・年）ごとの合計時間・グラフ・よくやったことを表示する"""
        # 最後に選んだ期間を覚えておき、次に開いたときも同じ期間で表示する
        self.dashboard_period = period or getattr(self, "dashboard_period", "week")
        csv_path = get_csv_path()
        no_record_message = "まだ記録がありません。\nまずは5分やってみましょう。"

        if not csv_path.exists():
            messagebox.showinfo("振り返り", no_record_message, parent=self.root)
            return

        try:
            records = load_records(csv_path)
        except Exception as e:
            messagebox.showerror("エラー", f"データの読み込み中にエラーが発生しました:\n{e}", parent=self.root)
            return

        if summarize_by_task(records).empty:
            messagebox.showinfo("振り返り", no_record_message, parent=self.root)
            return
        summary = summarize_period(records, self.dashboard_period)

        screen = self.make_screen("720x540")
        header = self.make_header(screen, "振り返り")
        self.make_tabs(
            header,
            [(key, label) for key, (label, _, _) in DASHBOARD_PERIODS.items()],
            self.dashboard_period,
            self.show_dashboard,
        ).pack(side="left", padx=(self.px(20), 0))

        # 合計時間（この期間・記録した日・累計）
        stats = tk.Frame(screen, bg=COLOR_BG)
        stats.pack(fill="x", pady=(0, 16))
        for label, value in [
            (summary["title"], format_hours_mins(summary["total"])),
            ("記録した日", f"{summary['active_days']} / {summary['span_days']}日"),
            (f"累計（{len(records)}回）", format_hours_mins(int(records["分"].sum()))),
        ]:
            cell = tk.Frame(stats, bg=COLOR_BG)
            cell.pack(side="left", expand=True, fill="x")
            make_label(cell, label, size=10, color=COLOR_MUTED).pack(anchor="w")
            make_label(cell, value, size=18, bold=True).pack(anchor="w")

        body = tk.Frame(screen, bg=COLOR_BG)
        body.pack(fill="both", expand=True)

        # よくやったこと（この期間の上位5件）
        tasks = tk.Frame(body, bg=COLOR_BG)
        tasks.pack(side="right", fill="y", padx=(24, 0))
        make_label(tasks, "よくやったこと", size=10, color=COLOR_MUTED).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        if summary["by_task"].empty:
            make_label(tasks, "この期間の記録はありません", size=11, color=COLOR_MUTED).grid(
                row=1, column=0, columnspan=2, sticky="w"
            )
        for row, (task, mins) in enumerate(summary["by_task"].head(5).items(), start=1):
            name = task if len(task) <= 10 else task[:9] + "…"
            make_label(tasks, name, size=11).grid(row=row, column=0, sticky="w", pady=2)
            make_label(tasks, format_hours_mins(int(mins)), size=11, color=COLOR_MUTED).grid(
                row=row, column=1, sticky="e", padx=(16, 0), pady=2
            )

        # 期間内の作業時間（週・月は日別、年は月別）
        chart = tk.Frame(body, bg=COLOR_BG)
        chart.pack(side="left", fill="both", expand=True)
        per = "月ごと" if self.dashboard_period == "year" else "日ごと"
        make_label(chart, f"{per}の作業時間（{summary['unit']}）", size=10, color=COLOR_MUTED).pack(anchor="w")

        # pyplot を使わず Figure を直接生成することで、Tkinter 埋め込み時のメモリリークを防ぐ
        fig = Figure(figsize=(4.6, 3.4), dpi=100 * self.scale, facecolor=COLOR_BG)
        ax = fig.add_subplot()
        ax.set_facecolor(COLOR_BG)
        values = summary["values"]
        ax.bar(range(len(values)), values, color=COLOR_ACCENT, width=0.6)

        # 日付が詰まらないよう間引く（最新の日・月は必ず表示）
        step = {"week": 1, "month": 5, "year": 1}[self.dashboard_period]
        ticks = list(range(len(values) - 1, -1, -step))[::-1]
        ax.set_xticks(ticks)
        ax.set_xticklabels([summary["labels"][i] for i in ticks])
        min_top = 1 if summary["unit"] == "時間" else 60
        ax.set_ylim(bottom=0, top=max(min_top, max(values) * 1.15))
        ax.tick_params(colors=COLOR_MUTED, labelsize=8, length=0)
        ax.grid(axis="y", color=COLOR_BORDER, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(COLOR_BORDER)
        if summary["total"] == 0:
            ax.text(
                0.5, 0.5, "この期間の記録はありません", ha="center", color=COLOR_MUTED, transform=ax.transAxes
            )
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=chart)
        canvas.draw()
        canvas.get_tk_widget().configure(bg=COLOR_BG, highlightthickness=0)
        canvas.get_tk_widget().pack(fill="both", expand=True)


def main():
    if platform.system() == "Windows":
        # python.exe とは別のアプリとして扱わせ、タスクバーに Python ではなくアプリのアイコンを出す
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JustDoIt.App")
        # 表示倍率が 100% 以外の PC で文字がぼやけないよう、Windows による拡大をやめて自前で拡大する
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    JustDoItApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
