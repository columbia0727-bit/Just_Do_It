"""記録一覧（記録の修正・削除。週次レポートに登録していれば、配信サービス側の記録も直す）"""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Callable

from justdoit import config, report_service
from justdoit.records import (
    DATETIME_FORMAT,
    Record,
    delete_record,
    list_records,
    update_record,
    validate_record,
)
from justdoit.ui.theme import C, make_button, make_entry, make_label, ui_font

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

HISTORY_SIZE = (560, 560)
MAX_ROWS = 200  # 一覧に出す件数（新しい順）


def show_history(app: JustDoItApp, back: Callable[[], None]) -> None:
    """記録一覧を表示する。「戻る」で back（振り返り画面）へ戻る"""
    screen = app.make_screen(HISTORY_SIZE)
    app.make_header(screen, "記録一覧", back=back)

    csv_path = config.get_csv_path()
    try:
        records = list_records(csv_path)[:MAX_ROWS]
    except OSError as e:
        messagebox.showerror("エラー", f"作業ログを読み込めませんでした:\n{e}", parent=app.root)
        return
    if not records:
        make_label(screen, "まだ記録がありません。", size=11, color=C.muted).pack(anchor="w")
        return

    # 表は残りの高さいっぱいに広げるので、下に置くものから先に配置する
    if report_service.is_registered():
        make_label(
            screen, "※ 直した内容は、週次レポートの記録にも反映されます。", size=9, color=C.muted
        ).pack(side="bottom", anchor="w")
    form = RecordForm(app, screen, csv_path, on_changed=lambda: show_history(app, back))

    make_label(screen, "直したい記録を選んでください", size=10, color=C.muted).pack(anchor="w", pady=(0, 6))
    table = build_table(app, screen, records)
    table.bind("<<TreeviewSelect>>", lambda event: form.load(records[table.index(table.selection()[0])]))


def build_table(app: JustDoItApp, screen: tk.Frame, records: list[Record]) -> ttk.Treeview:
    """日時・やったこと・時間の表（スクロールできる）"""
    style = ttk.Style()
    style.configure("Records.Treeview", font=ui_font(10), rowheight=app.px(24))
    style.configure("Records.Treeview.Heading", font=ui_font(10))

    frame = tk.Frame(screen, bg=screen["bg"])
    frame.pack(fill="both", expand=True)
    table = ttk.Treeview(
        frame, columns=("when", "task", "minutes"), show="headings", height=9, selectmode="browse", style="Records.Treeview"
    )
    for column, text, width, anchor in [
        ("when", "日時", 150, "w"),
        ("task", "やったこと", 250, "w"),
        ("minutes", "時間", 70, "e"),
    ]:
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


class RecordForm:
    """表で選んだ記録を直す・消すための入力欄"""

    def __init__(self, app: JustDoItApp, screen: tk.Frame, csv_path: Path, on_changed: Callable[[], None]):
        self.app = app
        self.csv_path = csv_path
        self.on_changed = on_changed  # 修正・削除したあとに一覧を表示し直す
        self.record: Record | None = None

        # 画面の下から「ボタン」「入力欄」の順に積む
        buttons = tk.Frame(screen, bg=screen["bg"])
        buttons.pack(side="bottom", fill="x", pady=(4, 8))
        make_button(buttons, "削除する", self.delete, width=110).pack(side="right")
        make_button(buttons, "修正を保存", self.save, primary=True, width=130).pack(side="right", padx=(0, 8))

        form = tk.Frame(screen, bg=screen["bg"])
        form.pack(side="bottom", fill="x", pady=(12, 0))
        make_label(form, "やったこと", size=11).grid(row=0, column=0, sticky="w")
        make_label(form, "時間（分）", size=11).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.task_entry = make_entry(form)
        self.task_entry.grid(row=1, column=0, sticky="ew", ipady=4)
        self.mins_entry = make_entry(form, width=8)
        self.mins_entry.grid(row=1, column=1, sticky="w", padx=(12, 0), ipady=4)
        form.columnconfigure(0, weight=1)
        self.error_label = make_label(form, size=10, color=C.error)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w")

        self.mins_entry.bind("<Return>", lambda event: self.save())
        self.task_entry.bind("<Return>", lambda event: self.save())

    def load(self, record: Record) -> None:
        self.record = record
        self.error_label.config(text="")
        for entry, value in [(self.task_entry, record.task), (self.mins_entry, str(record.minutes))]:
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
        task, minutes = result
        if (task, minutes) == (self.record.task, self.record.minutes):
            self.on_changed()  # 何も変わっていない
            return
        self.apply(
            lambda: update_record(self.csv_path, self.record.row_index, task, minutes),
            report_service.make_update(self.report_log(), task, minutes),
        )

    def delete(self) -> None:
        if self.record is None:
            self.error_label.config(text="一覧から記録を選んでください")
            return
        when = self.record.recorded_at.strftime("%m/%d %H:%M")
        if messagebox.askyesno(
            "削除の確認", f"{when}「{self.record.task}」（{self.record.minutes}分）を削除しますか？", parent=self.app.root
        ):
            self.apply(
                lambda: delete_record(self.csv_path, self.record.row_index),
                report_service.make_delete(self.report_log()),
            )

    def report_log(self) -> dict:
        """選んでいる記録を、配信サービスに送ったときと同じ形にする（サーバー側で探す手がかり）"""
        return report_service.make_log(
            self.record.recorded_at.strftime(DATETIME_FORMAT), self.record.task, self.record.minutes
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
                print(f"⚠️ 週次レポート用の変更を保存できませんでした: {e}")
            report_service.start_sync()
        self.on_changed()
