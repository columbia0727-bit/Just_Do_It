"""振り返り画面（期間ごとの合計時間・グラフ・よくやったこと、作業内容ごとの通算、記録一覧への入口）"""

from __future__ import annotations

from datetime import date
from functools import partial
import sys
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

# pyplot を使わず Figure を直接生成することで、Tkinter 埋め込み時のメモリリークを防ぐ
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from justdoit import config
from justdoit.records import (
    PERIODS,
    PeriodSummary,
    TaskTotal,
    compare_with_previous,
    format_hours_mins,
    load_records,
    summarize_all_time,
    summarize_by_task,
    summarize_period,
)
from justdoit.ui import history, timer
from justdoit.ui.theme import C, PillButton, make_button, make_label, make_link, make_tabs, text_width

if TYPE_CHECKING:
    import pandas as pd

    from justdoit.ui.app import JustDoItApp

DASHBOARD_SIZE = (750, 560)  # 右の列（よくやったこと）を決まった幅にしても、グラフが狭くならない幅・高さ
CHART_SIZE = (4.6, 3.4)  # グラフの大きさ（インチ。100% 表示で 1インチ = 100px）
SIDE_GAP = 24  # グラフと右の列の間
SCREEN_PADDING = 24  # 画面の左右の余白（app.make_screen と同じ）
EMPTY_SIZE = (420, 340)
TOP_TASKS = 5
MAX_TASK_NAME_LENGTH = 10
HISTORY_LINK_TEXT = "すべての記録を見る・直す  ›"
NO_TASKS_TEXT = "この期間の記録はありません"
TASK_TIME_GAP = 16  # よくやったことの、名前と時間の間
# グラフの横軸の目盛りを何本おきに出すか（月は30本あるので間引く）
TICK_STEP = {"week": 1, "month": 5, "year": 1}
TOTAL = "total"  # 期間の切り替えの「通算」（週・月・年と違い、前後に動かす期間はない）
TOTAL_ROWS = 8  # 通算の一覧に出す作業内容の数（それより後は「ほか ○件」にまとめる）
MAX_TOTAL_NAME_LENGTH = 12
TOTAL_BAR_WIDTH = 180
TOTAL_GAP = 16  # 通算の一覧の、列と列の間

# グラフの日本語フォント（OSごとに、入っているものを先頭から使う）
rcParams["font.sans-serif"] = {
    "darwin": ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Arial"],
    "win32": ["Yu Gothic", "Meiryo", "MS Gothic", "Arial"],
}.get(sys.platform, ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"])
rcParams["axes.unicode_minus"] = False


def show_dashboard(app: JustDoItApp, period: str | None = None, offset: int | None = None) -> None:
    """ローカルのCSVを読み込んで、選んだ期間（週・月・年・通算）の振り返りを表示する

    offset は何期間前を表示するか（0 が直近。「‹ 前へ」「次へ ›」や ← → キーで動かす）。
    """
    if period and period != app.dashboard_period:
        app.dashboard_period = period
        app.dashboard_offset = 0  # 週・月・年を切り替えたら、直近の期間から
    if offset is not None:
        app.dashboard_offset = max(0, offset)
    try:
        records = load_records(config.get_csv_path())
    except Exception as e:
        messagebox.showerror("エラー", f"データの読み込み中にエラーが発生しました:\n{e}", parent=app.root)
        return
    if summarize_by_task(records).empty:
        show_empty(app)
        return

    screen = app.make_screen(dashboard_size())
    header = app.make_header(screen, "振り返り")
    make_tabs(
        header,
        [(key, p.tab_label) for key, p in PERIODS.items()] + [(TOTAL, "通算")],
        app.dashboard_period,
        lambda key: show_dashboard(app, key),
    ).pack(side="left", padx=(app.px(20), 0))
    if app.dashboard_period == TOTAL:
        build_totals(app, screen, records)
        return

    summary = summarize_period(records, app.dashboard_period, offset=app.dashboard_offset)
    build_period_nav(app, header, records, summary)

    build_stats(app, screen, summary, records)

    body = tk.Frame(screen, bg=C.bg)
    body.pack(fill="both", expand=True)
    side = tk.Frame(body, bg=C.bg)
    side.pack(side="right", fill="y", padx=(SIDE_GAP, 0))
    # 右の列は、中身（作業内容の名前の長さ・件数）によらず同じ幅にする
    # （中身に合わせると、期間を切り替えるたびにグラフの幅とリンクの位置が左右に動くため）
    tk.Frame(side, bg=C.bg, width=app.px(side_width()), height=0).pack()
    build_top_tasks(side, summary).pack(fill="x")

    make_history_link(app, side)
    build_chart(app, body, summary).pack(side="left", fill="both", expand=True)


def make_history_link(app: JustDoItApp, parent: tk.Frame) -> None:
    """記録一覧への入口（記録の修正・削除は、振り返りの中から開く。メニューをシンプルに保つため）

    灰色の文字で右下の端に置いていたときは気づきにくかったので、一覧のすぐ下に、
    アクセント色と「›」で置く（ボタンにはせず、画面の静かさは保つ）
    """

    def open_history():
        history.show_history(app, back=lambda: show_dashboard(app))

    make_link(parent, HISTORY_LINK_TEXT, open_history, accent=True).pack(anchor="w", pady=(14, 0))


def build_period_nav(app: JustDoItApp, header: tk.Frame, records: pd.DataFrame, summary: PeriodSummary) -> None:
    """「‹ 前へ」「次へ ›」（← → キーでも動かせる）

    直近の期間では「次へ」、それより前に記録が無いときは「前へ」を押せない。
    押せないときも薄い色で出しておく（消すと、前の期間を見られること自体に気づけないため）。
    """
    nav = tk.Frame(header, bg=header["bg"])
    nav.pack(side="left", padx=(app.px(12), 0))
    has_earlier = records["日時"].min().date() < summary.start
    has_later = app.dashboard_offset > 0

    def go(step: int) -> None:
        if (step > 0 and has_earlier) or (step < 0 and has_later):
            show_dashboard(app, offset=app.dashboard_offset + step)

    for text, step, enabled in (("‹ 前へ", 1, has_earlier), ("次へ ›", -1, has_later)):
        if enabled:
            PillButton(nav, text, partial(go, step), kind="chip").pack(side="left", padx=(0, app.px(4)))
        else:
            PillButton(nav, text, None, kind="chip_disabled").pack(side="left", padx=(0, app.px(4)))
    app.bind_key("<Left>", lambda: go(1))
    app.bind_key("<Right>", lambda: go(-1))


def show_empty(app: JustDoItApp) -> None:
    """まだ記録がないときの振り返り画面（ダイアログではなく、画面の中で案内して最初の一歩を促す）"""
    screen = app.make_screen(EMPTY_SIZE)
    app.make_header(screen, "振り返り")
    make_label(screen, "まだ記録がありません", size=14, bold=True).pack(pady=(40, 4))
    make_label(screen, "記録すると、ここに作業時間のグラフが表示されます。", size=10, color=C.muted).pack()
    make_button(
        screen, "5分だけやってみる", lambda: timer.show_focus_timer(app, timer.FOCUS_SHORT_SECONDS), primary=True
    ).pack(side="bottom", fill="x")


def build_stats(app: JustDoItApp, screen: tk.Frame, summary: PeriodSummary, records: pd.DataFrame) -> None:
    """合計時間（この期間と、前の期間と比べた一言・記録した日・累計）"""
    comparison = compare_with_previous(records, app.dashboard_period, offset=app.dashboard_offset)
    note = (comparison.text, C.accent if comparison.increased else C.muted) if comparison else None
    make_stat_row(
        screen,
        [
            (summary.title, format_hours_mins(summary.total_minutes), note),
            ("記録した日", f"{summary.active_days} / {summary.span_days}日", None),
            (f"累計（{len(records)}回）", format_hours_mins(int(records["分"].sum())), None),
        ],
    )


def make_stat_row(screen: tk.Frame, cells: list[tuple[str, str, tuple[str, str] | None]]) -> None:
    """上に並べる大きな数字（見出し・数字・その下の小さな補足（文字, 色））"""
    stats = tk.Frame(screen, bg=C.bg)
    stats.pack(fill="x", pady=(0, 16))
    for label, value, note in cells:
        cell = tk.Frame(stats, bg=C.bg)
        # 補足がある欄だけ高くなるので、見出しの高さを上でそろえる
        cell.pack(side="left", expand=True, fill="x", anchor="n")
        make_label(cell, label, size=10, color=C.muted).pack(anchor="w")
        make_label(cell, value, size=18, bold=True).pack(anchor="w")
        if note:
            text, color = note
            make_label(cell, text, size=10, color=color).pack(anchor="w")


def build_totals(app: JustDoItApp, screen: tk.Frame, records: pd.DataFrame) -> None:
    """通算（全期間の合計と、作業内容ごとの通算の一覧）"""
    done = records[records["分"] > 0]
    first_day = done["日時"].min().date()
    days_since = (date.today() - first_day).days + 1
    make_stat_row(
        screen,
        [
            (f"通算（{len(done)}回）", format_hours_mins(int(done["分"].sum())), None),
            ("記録した日", f"{done['日時'].dt.date.nunique()}日", None),
            ("最初の記録", format_date(first_day), (f"今日で {days_since}日目", C.muted)),
        ],
    )
    totals = summarize_all_time(records)
    build_total_table(app, screen, totals[:TOTAL_ROWS])
    rest = totals[TOTAL_ROWS:]
    if rest:
        note = f"ほか {len(rest)}件 ・ {format_hours_mins(sum(t.minutes for t in rest))}"
        make_label(screen, note, size=10, color=C.muted).pack(anchor="w", pady=(6, 0))
    make_history_link(app, screen)


def build_total_table(app: JustDoItApp, parent: tk.Frame, totals: list[TaskTotal]) -> None:
    """作業内容ごとの通算の一覧（名前・帯・時間・回数・最初の記録）"""
    table = tk.Frame(parent, bg=C.bg)
    table.pack(fill="x")
    table.columnconfigure(1, weight=1)  # 帯の右の空きを広げ、数字を右端にそろえる
    # 名前の列は、いちばん長い名前が入る幅に決めておく（名前の長さで帯の始まりが左右にずれないように）
    table.columnconfigure(0, minsize=app.px(text_width(["国" * (MAX_TOTAL_NAME_LENGTH - 1) + "…"], 11)))
    for column, text in enumerate(["作業内容", "", "通算", "回数", "最初の記録"]):
        make_label(table, text, size=10, color=C.muted).grid(
            row=0, column=column, sticky="w" if column < 2 else "e", padx=(0 if column == 0 else TOTAL_GAP, 0),
            pady=(0, 6),
        )
    most = totals[0].minutes
    bar_width, bar_height = app.px(TOTAL_BAR_WIDTH), app.px(10)
    for row, total in enumerate(totals, start=1):
        name = total.task
        if len(name) > MAX_TOTAL_NAME_LENGTH:
            name = name[: MAX_TOTAL_NAME_LENGTH - 1] + "…"
        make_label(table, name, size=11).grid(row=row, column=0, sticky="w", pady=4)
        bar = tk.Canvas(table, width=bar_width, height=bar_height, bg=C.bg, highlightthickness=0)
        bar.grid(row=row, column=1, sticky="w", padx=(TOTAL_GAP, 0))
        bar.create_rectangle(0, 0, max(2, bar_width * total.minutes / most), bar_height, fill=C.accent, width=0)
        for column, (text, color) in enumerate(
            [
                (format_hours_mins(total.minutes), C.text),
                (f"{total.count}回", C.muted),
                (format_date(total.first_day), C.muted),
            ],
            start=2,
        ):
            make_label(table, text, size=11, color=color).grid(row=row, column=column, sticky="e", padx=(TOTAL_GAP, 0))


def format_date(day: date) -> str:
    """「2025/8/19」"""
    return f"{day.year}/{day.month}/{day.day}"


def dashboard_size() -> tuple[int, int]:
    """振り返りの画面の大きさ（週・月・年・通算で同じにする）

    右の列の幅は OS のフォントで変わり、Windows では DASHBOARD_SIZE の幅に収まらない。
    週・月・年だけ中身に合わせて広がると、通算に切り替えたときにウィンドウの幅が変わるので、
    グラフと右の列が入る幅を先に計算して、どのタブもその幅にする。
    """
    needed = round(CHART_SIZE[0] * 100) + SIDE_GAP + side_width() + SCREEN_PADDING * 2
    return max(DASHBOARD_SIZE[0], needed), DASHBOARD_SIZE[1]


def side_width() -> int:
    """右の列の幅（いちばん長い作業内容の名前と時間・リンク・「記録はありません」が入る幅）

    フォントは OS ごとに違うので、決まった数字ではなく、実際の文字の幅から決める。
    """
    longest_name = "国" * (MAX_TASK_NAME_LENGTH - 1) + "…"
    return max(
        text_width([longest_name], 11) + TASK_TIME_GAP + text_width(["999時間 59分"], 11),
        text_width([HISTORY_LINK_TEXT], 10),
        text_width([NO_TASKS_TEXT], 11),
    )


def build_top_tasks(parent: tk.Frame, summary: PeriodSummary) -> tk.Frame:
    """よくやったこと（この期間の上位5件）"""
    tasks = tk.Frame(parent, bg=C.bg)
    tasks.columnconfigure(0, weight=1)  # 時間は列の右端にそろえる
    make_label(tasks, "よくやったこと", size=10, color=C.muted).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    if summary.by_task.empty:
        make_label(tasks, NO_TASKS_TEXT, size=11, color=C.muted).grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
    for row, (task, mins) in enumerate(summary.by_task.head(TOP_TASKS).items(), start=1):
        name = task if len(task) <= MAX_TASK_NAME_LENGTH else task[: MAX_TASK_NAME_LENGTH - 1] + "…"
        make_label(tasks, name, size=11).grid(row=row, column=0, sticky="w", pady=2)
        make_label(tasks, format_hours_mins(int(mins)), size=11, color=C.muted).grid(
            row=row, column=1, sticky="e", padx=(TASK_TIME_GAP, 0), pady=2
        )
    return tasks


def build_chart(app: JustDoItApp, parent: tk.Frame, summary: PeriodSummary) -> tk.Frame:
    """期間内の作業時間の棒グラフ（週・月は日別、年は月別）"""
    chart = tk.Frame(parent, bg=C.bg)
    per = "月ごと" if app.dashboard_period == "year" else "日ごと"
    make_label(chart, f"{per}の作業時間（{summary.unit}）", size=10, color=C.muted).pack(anchor="w")

    fig = Figure(figsize=CHART_SIZE, dpi=100 * app.scale, facecolor=C.bg)
    ax = fig.add_subplot()
    ax.set_facecolor(C.bg)
    values = summary.values
    ax.bar(range(len(values)), values, color=C.accent, width=0.6)

    # 日付が詰まらないよう間引く（最新の日・月は必ず表示）
    ticks = list(range(len(values) - 1, -1, -TICK_STEP[app.dashboard_period]))[::-1]
    ax.set_xticks(ticks)
    ax.set_xticklabels([summary.labels[i] for i in ticks])
    # 記録が少なくても棒が天井に張り付かないよう、縦軸の最小の高さを決めておく
    min_top = 1 if summary.unit == "時間" else 60
    ax.set_ylim(bottom=0, top=max(min_top, max(values) * 1.15))

    ax.tick_params(colors=C.muted, labelsize=8, length=0)
    ax.grid(axis="y", color=C.border, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(C.border)
    if summary.total_minutes == 0:
        ax.text(0.5, 0.5, "この期間の記録はありません", ha="center", color=C.muted, transform=ax.transAxes)
    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=chart)
    canvas.draw()
    canvas.get_tk_widget().configure(bg=C.bg, highlightthickness=0)
    canvas.get_tk_widget().pack(fill="both", expand=True)
    return chart
