"""記録一覧（記録の修正・削除。週次レポートに登録していれば、配信サービス側の記録も直す）"""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Literal

from justdoit import config, report_service
from justdoit.records import (
    DATETIME_FORMAT,
    Record,
    delete_record,
    group_by_month,
    list_records,
    update_record,
    validate_record,
    validate_when,
)
from justdoit.ui import confirm
from justdoit.ui.theme import C, make_button, make_entry, make_label, make_select, ui_font

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

logger = logging.getLogger(__name__)
HISTORY_SIZE = (560, 580)


def show_history(app: JustDoItApp, back: Callable[[], None]) -> None:
    """記録一覧を表示する。「戻る」で back（振り返り画面）へ戻る

    記録は月ごとに切り替えて表示する（同期で1年分の記録があっても、どの月の記録も直せるように）。
    """
    screen = app.make_screen(HISTORY_SIZE)
    app.make_header(screen, "記録一覧", back=back)

    csv_path = config.get_csv_path()
    try:
        months = group_by_month(list_records(csv_path))
    except OSError as e:
        messagebox.showerror("エラー", f"作業ログを読み込めませんでした:\n{e}", parent=app.root)
        return
    if not months:
        make_label(screen, "まだ記録がありません。", size=11, color=C.muted).pack(anchor="w")
        return
    # 前に選んでいた月を表示する（その月の記録をすべて消した場合などは、いちばん新しい月）
    month_keys = [key for key, _ in months]
    index = month_keys.index(app.history_month) if app.history_month in month_keys else 0
    records = months[index][1]

    # 表は残りの高さいっぱいに広げるので、下に置くものから先に配置する
    if report_service.is_registered():
        make_label(
            screen, "※ 直した内容は、週次レポートの記録にも反映されます。", size=9, color=C.muted
        ).pack(side="bottom", anchor="w")
    form = RecordForm(app, screen, csv_path, on_changed=lambda: show_history(app, back))

    def choose_month(new_index: int) -> None:
        app.history_month = month_keys[new_index]
        show_history(app, back)

    top = tk.Frame(screen, bg=screen["bg"])
    top.pack(fill="x", pady=(0, 8))
    make_select(
        top, [f"{year}年{month}月（{len(items)}件）" for (year, month), items in months], index, choose_month
    ).pack(side="left")
    make_label(top, "直したい記録を選んでください", size=10, color=C.muted).pack(side="left", padx=(12, 0))
    table = build_table(app, screen, records)
    table.bind("<<TreeviewSelect>>", lambda event: form.load(records[table.index(table.selection()[0])]))
    # Tab キーで選ぶ順（重なり順）を、見た目どおり「月 → 表 → 入力欄 → ボタン」にそろえる
    for frame in (top, table.master, form.fields, form.buttons):
        frame.lift()


def build_table(app: JustDoItApp, screen: tk.Frame, records: list[Record]) -> ttk.Treeview:
    """日時・やったこと・時間の表（スクロールできる）"""
    style = ttk.Style()
    style.configure("Records.Treeview", font=ui_font(10), rowheight=app.px(24))
    style.configure("Records.Treeview.Heading", font=ui_font(10))

    frame = tk.Frame(screen, bg=screen["bg"])
    frame.pack(fill="both", expand=True)
    table = ttk.Treeview(
        frame,
        columns=("when", "task", "minutes"),
        show="headings",
        height=9,
        selectmode="browse",
        style="Records.Treeview",
    )
    columns: list[tuple[str, str, int, Literal["w", "e"]]] = [
        ("when", "日時", 150, "w"),
        ("task", "やったこと", 250, "w"),
        ("minutes", "時間", 70, "e"),
    ]
    for column, text, width, anchor in columns:
        table.heading(column, text=text, anchor=anchor)
        table.column(column, width=app.px(width), anchor=anchor, stretch=column == "task")
    for record in records:
        table.insert(
            "", "end", values=(record.recorded_at.strftime("%Y/%m/%d %H:%M"), record.task, f"{record.minutes}分")
        )

    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    table.pack(side="left", fill="both", expand=True)
    return table


def report_log(record: Record) -> dict:
    """記録を、配信サービスに送ったときと同じ形にする（サーバー側で探す手がかり）"""
    return report_service.make_log(record.recorded_at.strftime(DATETIME_FORMAT), record.task, record.minutes)


class RecordForm:
    """表で選んだ記録を直す・消すための入力欄"""

    def __init__(self, app: JustDoItApp, screen: tk.Frame, csv_path: Path, on_changed: Callable[[], None]):
        self.app = app
        self.csv_path = csv_path
        self.on_changed = on_changed  # 修正・削除したあとに一覧を表示し直す
        self.record: Record | None = None

        # 画面の下から「ボタン」「入力欄」の順に積む
        self.buttons = buttons = tk.Frame(screen, bg=screen["bg"])
        buttons.pack(side="bottom", fill="x", pady=(4, 8))
        delete_button = make_button(buttons, "削除する", self.delete, width=110)
        delete_button.pack(side="right")
        make_button(buttons, "修正を保存", self.save, primary=True, width=130).pack(side="right", padx=(0, 8))
        delete_button.lift()  # Tab キーでは、左にある「修正を保存」を先に選ぶ

        self.fields = form = tk.Frame(screen, bg=screen["bg"])
        form.pack(side="bottom", fill="x", pady=(12, 0))
        for column, text in enumerate(["やったこと", "日付", "時刻", "時間（分）"]):
            make_label(form, text, size=11).grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 10, 0))
        self.task_entry = make_entry(form)
        self.task_entry.grid(row=1, column=0, sticky="ew", ipady=4)
        self.date_entry = make_entry(form, width=10)
        self.date_entry.grid(row=1, column=1, sticky="w", padx=(10, 0), ipady=4)
        self.time_entry = make_entry(form, width=6)
        self.time_entry.grid(row=1, column=2, sticky="w", padx=(10, 0), ipady=4)
        self.mins_entry = make_entry(form, width=6)
        self.mins_entry.grid(row=1, column=3, sticky="w", padx=(10, 0), ipady=4)
        form.columnconfigure(0, weight=1)
        self.error_label = make_label(form, size=10, color=C.error)
        self.error_label.grid(row=2, column=0, columnspan=4, sticky="w")

        for entry in (self.task_entry, self.date_entry, self.time_entry, self.mins_entry):
            entry.bind("<Return>", lambda event: self.save())

    def load(self, record: Record) -> None:
        self.record = record
        self.error_label.config(text="")
        for entry, value in [
            (self.task_entry, record.task),
            (self.date_entry, f"{record.recorded_at:%Y/%m/%d}"),
            (self.time_entry, f"{record.recorded_at:%H:%M}"),
            (self.mins_entry, str(record.minutes)),
        ]:
            entry.delete(0, "end")
            entry.insert(0, value)

    def save(self) -> None:
        if self.record is None:
            self.error_label.config(text="一覧から記録を選んでください")
            return
        result = validate_record(self.task_entry.get(), self.mins_entry.get())
        if isinstance(result, str):
            self.error_label.config(text=result)
            return
        when = validate_when(self.date_entry.get(), self.time_entry.get())
        if isinstance(when, str):
            self.error_label.config(text=when)
            return
        task, minutes = result
        record = self.record
        # 日時は分の単位で入力するので、秒は元の記録のものを残す（日時を変えていなければ同じ記録のまま）
        when = when.replace(second=record.recorded_at.second)
        if (task, minutes, when) == (record.task, record.minutes, record.recorded_at):
            self.on_changed()  # 何も変わっていない
            return
        new_datetime = when.strftime(DATETIME_FORMAT)
        self.apply(
            lambda: update_record(self.csv_path, record.row_index, task, minutes, recorded_at=when),
            report_service.make_update(report_log(record), task, minutes, new_datetime=new_datetime),
        )

    def delete(self) -> None:
        if self.record is None:
            self.error_label.config(text="一覧から記録を選んでください")
            return
        record = self.record
        when = record.recorded_at.strftime("%m/%d %H:%M")
        if confirm.ask(
            self.app,
            "記録を削除しますか？",
            f"{when}「{record.task}」（{record.minutes}分）",
            [confirm.Choice("削除する", True), confirm.Choice("やめておく", False, safe=True)],
        ):
            self.apply(
                lambda: delete_record(self.csv_path, record.row_index),
                report_service.make_delete(report_log(record)),
            )

    def apply(self, change: Callable[[], None], report_item: dict) -> None:
        """CSV を書き換えて一覧を表示し直す（Excel で開いているなどで書き込めなければ知らせる）

        週次レポートに登録していれば、同じ変更を配信サービスにも送る（送信待ちキュー経由なので、
        オフラインでも次につながったときに反映される）。
        """
        try:
            change()
        except (OSError, IndexError) as e:
            messagebox.showerror(
                "保存エラー",
                f"作業ログを書き換えられませんでした:\n{e}\n\n"
                "作業ログを Excel などで開いている場合は、閉じてからもう一度お試しください。",
                parent=self.app.root,
            )
            return
        if report_service.is_registered():
            try:
                report_service.enqueue_logs(config.get_report_queue_path(), [report_item])
            except OSError as e:
                logger.warning("週次レポート用の変更を保存できませんでした: %s", e)
            report_service.start_sync()
        self.on_changed()
