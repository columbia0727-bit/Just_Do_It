"""振り返り画面（期間ごとの合計時間・グラフ・よくやったこと、記録一覧への入口）"""

from __future__ import annotations

import platform
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
    format_hours_mins,
    load_records,
    summarize_by_task,
    summarize_period,
)
from justdoit.ui import history, timer
from justdoit.ui.theme import C, PillButton, make_button, make_label, make_link, make_tabs

if TYPE_CHECKING:
    import pandas as pd

    from justdoit.ui.app import JustDoItApp

DASHBOARD_SIZE = (720, 540)
EMPTY_SIZE = (420, 340)
TOP_TASKS = 5
MAX_TASK_NAME_LENGTH = 10
# グラフの横軸の目盛りを何本おきに出すか（月は30本あるので間引く）
TICK_STEP = {"week": 1, "month": 5, "year": 1}

# グラフの日本語フォント（OSごとに、入っているものを先頭から使う）
rcParams["font.sans-serif"] = {
    "Darwin": ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Arial"],
    "Windows": ["Yu Gothic", "Meiryo", "MS Gothic", "Arial"],
}.get(platform.system(), ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"])
rcParams["axes.unicode_minus"] = False


def show_dashboard(app: JustDoItApp, period: str | None = None, offset: int | None = None) -> None:
    """ローカルのCSVを読み込んで、選んだ期間（週・月・年）の振り返りを表示する

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

    summary = summarize_period(records, app.dashboard_period, offset=app.dashboard_offset)

    screen = app.make_screen(DASHBOARD_SIZE)
    header = app.make_header(screen, "振り返り")
    make_tabs(
        header,
        [(key, p.tab_label) for key, p in PERIODS.items()],
        app.dashboard_period,
        lambda key: show_dashboard(app, key),
    ).pack(side="left", padx=(app.px(20), 0))
    build_period_nav(app, header, records, summary)

    build_stats(screen, summary, records)

    body = tk.Frame(screen, bg=C.bg)
    body.pack(fill="both", expand=True)
    side = tk.Frame(body, bg=C.bg)
    side.pack(side="right", fill="y", padx=(24, 0))
    build_top_tasks(side, summary).pack(anchor="w")
    # 記録の修正・削除は、振り返りの中から開く（メニューをシンプルに保つため）
    def open_history():
        history.show_history(app, back=lambda: show_dashboard(app))

    make_link(side, "すべての記録を見る・直す", open_history).pack(side="bottom", anchor="w", pady=(0, 8))
    build_chart(app, body, summary).pack(side="left", fill="both", expand=True)


def build_period_nav(app: JustDoItApp, header: tk.Frame, records: pd.DataFrame, summary: PeriodSummary) -> None:
    """「‹ 前へ」「次へ ›」（← → キーでも動かせる）。直近の期間では「次へ」、記録が無い過去では「前へ」を出さない"""
    nav = tk.Frame(header, bg=header["bg"])
    nav.pack(side="left", padx=(app.px(12), 0))
    has_earlier = records["日時"].min().date() < summary.start
    has_later = app.dashboard_offset > 0

    def go(step: int) -> None:
        if (step > 0 and has_earlier) or (step < 0 and has_later):
            show_dashboard(app, offset=app.dashboard_offset + step)

    if has_earlier:
        PillButton(nav, "‹ 前へ", lambda: go(1), kind="chip").pack(side="left", padx=(0, app.px(4)))
    if has_later:
        PillButton(nav, "次へ ›", lambda: go(-1), kind="chip").pack(side="left")
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


def build_stats(screen: tk.Frame, summary: PeriodSummary, records: pd.DataFrame) -> None:
    """合計時間（この期間・記録した日・累計）"""
    stats = tk.Frame(screen, bg=C.bg)
    stats.pack(fill="x", pady=(0, 16))
    for label, value in [
        (summary.title, format_hours_mins(summary.total_minutes)),
        ("記録した日", f"{summary.active_days} / {summary.span_days}日"),
        (f"累計（{len(records)}回）", format_hours_mins(int(records["分"].sum()))),
    ]:
        cell = tk.Frame(stats, bg=C.bg)
        cell.pack(side="left", expand=True, fill="x")
        make_label(cell, label, size=10, color=C.muted).pack(anchor="w")
        make_label(cell, value, size=18, bold=True).pack(anchor="w")


def build_top_tasks(parent: tk.Frame, summary: PeriodSummary) -> tk.Frame:
    """よくやったこと（この期間の上位5件）"""
    tasks = tk.Frame(parent, bg=C.bg)
    make_label(tasks, "よくやったこと", size=10, color=C.muted).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    if summary.by_task.empty:
        make_label(tasks, "この期間の記録はありません", size=11, color=C.muted).grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
    for row, (task, mins) in enumerate(summary.by_task.head(TOP_TASKS).items(), start=1):
        name = task if len(task) <= MAX_TASK_NAME_LENGTH else task[: MAX_TASK_NAME_LENGTH - 1] + "…"
        make_label(tasks, name, size=11).grid(row=row, column=0, sticky="w", pady=2)
        make_label(tasks, format_hours_mins(int(mins)), size=11, color=C.muted).grid(
            row=row, column=1, sticky="e", padx=(16, 0), pady=2
        )
    return tasks


def build_chart(app: JustDoItApp, parent: tk.Frame, summary: PeriodSummary) -> tk.Frame:
    """期間内の作業時間の棒グラフ（週・月は日別、年は月別）"""
    chart = tk.Frame(parent, bg=C.bg)
    per = "月ごと" if app.dashboard_period == "year" else "日ごと"
    make_label(chart, f"{per}の作業時間（{summary.unit}）", size=10, color=C.muted).pack(anchor="w")

    fig = Figure(figsize=(4.6, 3.4), dpi=100 * app.scale, facecolor=C.bg)
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
