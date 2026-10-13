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
DASHBOARD_DAYS = 14

MENU_GEOMETRY = "320x340"

# OSに合わせて日本語フォントを切り替える
if platform.system() == "Darwin":  # Macの場合
    rcParams["font.sans-serif"] = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Arial"]
elif platform.system() == "Windows":  # Windowsの場合
    rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "MS Gothic", "Arial"]
else:  # Linux等の場合
    rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


# ==========================================
# 保存先・設定まわり
# ==========================================
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


def get_gas_url():
    """GAS の WebアプリURL（環境変数 JUSTDOIT_GAS_URL が設定ファイルより優先）"""
    return os.environ.get("JUSTDOIT_GAS_URL") or load_config().get("gas_url", "")


def is_valid_gas_url(url):
    return url.startswith("https://script.google.com/")


# ==========================================
# 記録の保存・送信
# ==========================================
def append_record_to_csv(csv_path, now_str, task, duration_mins):
    """ローカルCSVに1行追記する(newline=""で空行を防止、utf-8-sigでExcel互換)"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([now_str, task, f"{duration_mins}分"])


def send_to_gas(gas_url, payload):
    """GASにPOSTリクエストを送信してスプレッドシートに記録する（別スレッドから呼ぶ）"""
    try:
        req = urllib.request.Request(
            gas_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=GAS_TIMEOUT_SECONDS) as res:
            result = json.loads(res.read().decode("utf-8"))

        if result.get("status") == "success":
            print("➔ スプレッドシートに追加しました")
        else:
            print(f"⚠️ スプレッドシート追加エラー: {result.get('message', '不明')}")
    except Exception as e:
        print(f"❌ スプレッドシート通信エラー: {e}")


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


def summarize_by_day(records, days=DASHBOARD_DAYS, today=None):
    """直近 days 日分の日別合計（記録がない日も0分として含める）"""
    today = (today or datetime.now()).date()
    index = pd.date_range(today - timedelta(days=days - 1), today).date
    daily = records.groupby(records["日時"].dt.date)["分"].sum()
    return daily.reindex(index, fill_value=0)


def format_hours_mins(total_mins):
    return f"{total_mins // 60}時間 {total_mins % 60}分"


# ==========================================
# GUI
# ==========================================
class JustDoItApp:

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.after_id = None
        self.running = False

        # 画面中央に配置する
        window_width, window_height = 320, 340
        x = (self.root.winfo_screenwidth() - window_width) // 2
        y = (self.root.winfo_screenheight() - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.create_main_menu()

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

    def create_main_menu(self):
        """起動時のメインメニュー（ボタン一覧）"""
        self.clear_window()
        self.root.geometry(MENU_GEOMETRY)

        tk.Label(self.root, text="さあ、どうする？", font=("", 16, "bold")).pack(pady=15)

        tk.Button(
            self.root,
            text="🔥 5分やる",
            width=25,
            command=lambda: self.start_timer(FOCUS_SHORT_SECONDS, "5分集中"),
        ).pack(pady=5)

        tk.Button(
            self.root,
            text="🍅 25分やる",
            width=25,
            command=lambda: self.start_timer(FOCUS_LONG_SECONDS, "25分集中"),
        ).pack(pady=5)

        tk.Button(
            self.root,
            text="📝 記録する（手動）",
            width=25,
            command=self.manual_record_flow,
        ).pack(pady=5)

        tk.Button(
            self.root,
            text="📊 ダッシュボードを表示",
            width=25,
            bg="#e0f7fa",
            command=self.show_dashboard,
        ).pack(pady=10)

        tk.Button(
            self.root,
            text="⚙️ 設定",
            width=25,
            command=self.show_settings,
        ).pack(pady=5)

        sync_text = "☁️ スプレッドシート連携: ON" if get_gas_url() else "💾 ローカル保存のみ"
        tk.Label(self.root, text=sync_text, fg="gray").pack(pady=5)

    # ---------- 集中タイマー ----------
    def start_timer(self, duration_seconds, timer_name):
        """タイマーを開始する処理"""
        self.clear_window()
        self.timer_type = timer_name
        self.target_seconds = duration_seconds
        self.start_time = datetime.now()
        self.running = True

        self.label = tk.Label(self.root, text=f"集中... ({timer_name})", font=("", 14))
        self.label.pack(pady=20)

        # ⏹️ 途中でやめるボタン（確認なしで即座に経過時間を記録して戻る）
        tk.Button(
            self.root,
            text="途中でやめる（記録する）",
            bg="#ffebee",
            command=self.abort_timer,
            width=25,
        ).pack(pady=5)

        tk.Button(
            self.root,
            text="記録せずにメニューに戻る",
            command=self.create_main_menu,
            width=25,
        ).pack(pady=5)

        self.check_time()

    def check_time(self):
        """1秒ごとに残り時間をチェックするループ処理"""
        if not self.running:
            return
        elapsed = datetime.now() - self.start_time
        remaining = self.target_seconds - int(elapsed.total_seconds())

        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            self.label.config(text=f"集中！残り {mins}分 {secs:02d}秒")
            self.after_id = self.root.after(1000, self.check_time)
        else:
            self.after_id = None
            self.time_up()

    def abort_timer(self):
        """途中でやめるボタンが押されたときの処理（確認なしで直ちに経過時間を記録）"""
        self.cancel_timer()

        elapsed_secs = int((datetime.now() - self.start_time).total_seconds())
        # 1分未満で中断した場合でも最低「1分」として切り上げる
        duration_mins = max(1, (elapsed_secs + 59) // 60)

        self.bring_to_front(True)
        task = simpledialog.askstring(
            "中断記録",
            f"ここまで約{duration_mins}分経過しました。\n今回の作業内容は何ですか？",
            parent=self.root,
        )
        self.bring_to_front(False)

        # 作業内容が入力された場合のみ、記録を保存する
        if task and task.strip():
            self.save_record(task.strip(), duration_mins)

        self.create_main_menu()

    def time_up(self):
        """タイマー終了時の処理"""
        self.running = False
        self.root.bell()
        self.bring_to_front(True)
        messagebox.showinfo("時間です", "終了！お疲れ様でした。", parent=self.root)

        # 作業内容を入力するための「専用サブウインドウ (Toplevel)」を作成
        input_win = tk.Toplevel(self.root)
        input_win.title("作業完了入力")
        input_win.geometry("280x180")
        input_win.attributes("-topmost", True)
        input_win.grab_set()

        tk.Label(input_win, text="今回の作業内容は何ですか？").pack(pady=(15, 0))
        task_entry = tk.Entry(input_win, width=30)
        task_entry.pack(pady=5)
        task_entry.focus_set()  # 自動でカーソルをテキストボックスに合わせる

        def save_and_close(event=None):
            task = task_entry.get().strip()
            if not task:
                messagebox.showwarning(
                    "入力エラー", "作業内容を入力してください。", parent=input_win
                )
                return

            duration_mins = self.target_seconds // 60
            self.save_record(task, duration_mins)
            messagebox.showinfo(
                "保存完了",
                f"「{task} ({duration_mins}分)」の記録を保存しました！",
                parent=input_win,
            )

            # 入力ウインドウを閉じ、最前面固定を解除して、休憩タイマーへ移行
            input_win.destroy()
            self.bring_to_front(False)
            self.start_break_timer()

        def close_without_saving():
            input_win.destroy()
            self.bring_to_front(False)
            self.create_main_menu()

        tk.Button(input_win, text="保存する", command=save_and_close, width=15).pack(pady=10)
        task_entry.bind("<Return>", save_and_close)
        # ✖ボタンでウインドウが閉じられた場合は記録せずメインメニューに戻る
        input_win.protocol("WM_DELETE_WINDOW", close_without_saving)

    # ---------- 休憩タイマー ----------
    def start_break_timer(self):
        """10分間の休憩タイマー処理"""
        self.clear_window()
        self.break_start_time = datetime.now()
        self.running = True

        self.break_label = tk.Label(self.root, text="", font=("", 14))
        self.break_label.pack(pady=30)

        tk.Button(
            self.root,
            text="休憩を終えてメニューに戻る",
            command=self.create_main_menu,
            width=25,
        ).pack(pady=10)

        self.check_break_time()

    def check_break_time(self):
        """休憩時間のカウントダウン"""
        if not self.running:
            return
        elapsed = datetime.now() - self.break_start_time
        remaining = BREAK_SECONDS - int(elapsed.total_seconds())

        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            self.break_label.config(
                text=f"休憩中... (最長{BREAK_SECONDS // 60}分)\n残り {mins}分 {secs:02d}秒"
            )
            self.after_id = self.root.after(1000, self.check_break_time)
        else:
            self.after_id = None
            self.running = False
            self.root.bell()
            self.bring_to_front(True)
            messagebox.showinfo(
                "休憩終了",
                f"{BREAK_SECONDS // 60}分経過しました！次の作業へ移りましょう。",
                parent=self.root,
            )
            self.bring_to_front(False)
            self.create_main_menu()

    # ---------- 手動記録 ----------
    def manual_record_flow(self):
        """手動記録用の画面に切り替える"""
        self.clear_window()

        tk.Label(self.root, text="手動記録", font=("", 16, "bold")).pack(pady=15)

        tk.Label(self.root, text="やった内容は何ですか？").pack(pady=(5, 0))
        task_entry = tk.Entry(self.root, width=25)
        task_entry.pack(pady=5)
        task_entry.focus_set()

        tk.Label(self.root, text="何分間実施しましたか？（数字のみ）").pack(pady=(5, 0))
        mins_entry = tk.Entry(self.root, width=15)
        mins_entry.pack(pady=5)

        def save_and_back(event=None):
            task = task_entry.get().strip()
            mins_str = mins_entry.get().strip()

            if not task:
                messagebox.showwarning(
                    "入力エラー", "作業内容を入力してください。", parent=self.root
                )
                return

            if not mins_str.isdigit() or not 1 <= int(mins_str) <= MAX_MANUAL_MINUTES:
                messagebox.showwarning(
                    "入力エラー",
                    f"実施時間は 1〜{MAX_MANUAL_MINUTES} の整数（分）で入力してください。",
                    parent=self.root,
                )
                mins_entry.focus_set()
                return

            duration = int(mins_str)
            self.save_record(task, duration)
            messagebox.showinfo(
                "保存完了",
                f"「{task} ({duration}分)」の記録を保存しました！",
                parent=self.root,
            )
            self.create_main_menu()

        tk.Button(self.root, text="保存する", command=save_and_back, width=25).pack(pady=10)
        tk.Button(
            self.root, text="メニューに戻る", command=self.create_main_menu, width=25
        ).pack(pady=5)

        # Enterキーでの保存対応
        task_entry.bind("<Return>", lambda event: mins_entry.focus_set())
        mins_entry.bind("<Return>", save_and_back)

    # ---------- 保存 ----------
    def save_record(self, task, duration_mins):
        """ローカルCSVへの保存 ＆ Googleスプレッドシート（GAS）への自動送信"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            append_record_to_csv(get_csv_path(), now_str, task, duration_mins)
        except OSError as e:
            messagebox.showerror(
                "保存エラー", f"作業ログを保存できませんでした:\n{e}", parent=self.root
            )
            return
        print(f"【ローカル保存完了】{now_str} - {task} ({duration_mins}分)")

        # GAS連携が設定されている場合のみ、UIを止めないよう別スレッドで送信
        gas_url = get_gas_url()
        if gas_url:
            payload = {"datetime": now_str, "task": task, "duration": f"{duration_mins}分"}
            threading.Thread(target=send_to_gas, args=(gas_url, payload), daemon=True).start()

    # ---------- 設定 ----------
    def show_settings(self):
        """GAS の WebアプリURL を設定する画面"""
        self.clear_window()
        self.root.geometry("420x300")

        tk.Label(self.root, text="⚙️ 設定", font=("", 16, "bold")).pack(pady=15)
        tk.Label(
            self.root,
            text="Googleスプレッドシート連携用の GAS WebアプリURL\n（空欄ならローカル保存のみ）",
        ).pack(pady=(5, 0))

        url_entry = tk.Entry(self.root, width=50)
        url_entry.insert(0, load_config().get("gas_url", ""))
        url_entry.pack(pady=5)
        url_entry.focus_set()

        tk.Label(self.root, text=f"保存先: {get_data_dir()}", fg="gray", wraplength=400).pack(
            pady=5
        )

        def save_and_back(event=None):
            url = url_entry.get().strip()
            if url and not is_valid_gas_url(url):
                messagebox.showwarning(
                    "入力エラー",
                    "URL は https://script.google.com/ から始まる GAS の WebアプリURL を入力してください。",
                    parent=self.root,
                )
                return
            config = load_config()
            config["gas_url"] = url
            try:
                save_config(config)
            except OSError as e:
                messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=self.root)
                return
            messagebox.showinfo("保存完了", "設定を保存しました。", parent=self.root)
            self.create_main_menu()

        tk.Button(self.root, text="保存する", command=save_and_back, width=25).pack(pady=10)
        tk.Button(
            self.root, text="メニューに戻る", command=self.create_main_menu, width=25
        ).pack(pady=5)
        url_entry.bind("<Return>", save_and_back)

    # ---------- ダッシュボード ----------
    def show_dashboard(self):
        """ローカルのCSVを読み込んでTkinter画面内にグラフを埋め込んで表示する"""
        csv_path = get_csv_path()

        if not csv_path.exists():
            messagebox.showwarning(
                "警告",
                f"作業記録ファイルが見つかりません:\n{csv_path}\nまずは記録を保存してください！",
            )
            return

        try:
            records = load_records(csv_path)
        except Exception as e:
            messagebox.showerror("エラー", f"データの読み込み中にエラーが発生しました:\n{e}")
            return

        by_task = summarize_by_task(records)
        if by_task.empty:
            messagebox.showinfo("情報", "集計できる有効な時間データが見つかりませんでした。")
            return
        by_day = summarize_by_day(records)

        self.clear_window()
        self.root.geometry("820x600")

        tk.Label(self.root, text="📊 作業時間分析ダッシュボード", font=("", 14, "bold")).pack(
            pady=10
        )

        today_mins = int(by_day.iloc[-1])
        week_mins = int(by_day.iloc[-7:].sum())
        total_mins = int(records["分"].sum())
        tk.Label(
            self.root,
            text=(
                f"今日: {format_hours_mins(today_mins)}　｜　"
                f"直近7日: {format_hours_mins(week_mins)}　｜　"
                f"累計: {format_hours_mins(total_mins)}（{len(records)}回）"
            ),
        ).pack()

        fig = Figure(figsize=(8, 4.4), dpi=100)
        ax_pie, ax_bar = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.3]})

        # 作業内容が多すぎると円グラフが読めないので、上位以外は「その他」にまとめる
        top_n = 6
        pie_data = by_task.head(top_n)
        if len(by_task) > top_n:
            pie_data = pd.concat([pie_data, pd.Series({"その他": by_task.iloc[top_n:].sum()})])
        ax_pie.pie(
            pie_data.values,
            labels=pie_data.index,
            # 小さい扇形はラベルが重なるので割合を表示しない
            autopct=lambda pct: f"{pct:.1f}%" if pct >= 5 else "",
            startangle=90,
            counterclock=False,
            colors=[f"C{i}" for i in range(len(pie_data))],
            wedgeprops={"edgecolor": "white"},
        )
        ax_pie.set_title("作業内容別 時間割合")

        ax_bar.bar([d.strftime("%m/%d") for d in by_day.index], by_day.values, color="#26a69a")
        ax_bar.set_title(f"日別 作業時間（直近{DASHBOARD_DAYS}日）")
        ax_bar.set_ylabel("分")
        ax_bar.set_ylim(bottom=0, top=max(60, by_day.max() * 1.15))
        if by_day.sum() == 0:
            ax_bar.text(0.5, 0.5, "直近の記録はありません", ha="center", transform=ax_bar.transAxes)
        ax_bar.tick_params(axis="x", labelrotation=60, labelsize=8)
        ax_bar.spines[["top", "right"]].set_visible(False)

        fig.tight_layout()

        # ボタンを先に下端へ配置し、グラフが大きくても隠れないようにする
        tk.Button(self.root, text="メニューに戻る", width=20, command=self.create_main_menu).pack(
            side="bottom", pady=10
        )

        canvas = FigureCanvasTkAgg(fig, master=self.root)
        canvas.draw()
        canvas.get_tk_widget().pack(pady=5, fill="both", expand=True)


def main():
    root = tk.Tk()
    JustDoItApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
