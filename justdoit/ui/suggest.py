"""作業内容の入力欄に、前に使った名前を候補として出す（「英語」「英語の勉強」のような名前のばらつきを防ぐ）

候補は押したときだけ入力欄に入る。Enter キーは今までどおり保存や次の欄への移動に使う（入力の流れを変えないため）。
"""

from __future__ import annotations

from functools import partial
import tkinter as tk

from justdoit.records import suggest_tasks
from justdoit.ui.theme import C, make_label, px

MAX_SUGGESTIONS = 4


class TaskSuggestions:
    """入力欄のすぐ下に重ねて出す候補の一覧（選ぶ・欄から離れる・Esc キーで消える）"""

    def __init__(self, entry: tk.Entry, counts: list[tuple[str, int]]):
        self.entry = entry
        self.counts = counts  # (作業内容, 記録した回数) の多い順
        self.box: tk.Frame | None = None
        self.choosing = False
        self.text = tk.StringVar(entry, value=entry.get())
        entry.configure(textvariable=self.text)
        self.text.trace_add("write", lambda *args: self.update())
        entry.bind("<FocusOut>", lambda event: self.hide(), add="+")
        entry.bind("<Escape>", self.on_escape, add="+")

    def update(self) -> None:
        # 入力欄で打っているときだけ出す（記録一覧で記録を選んで欄に入ったときなどは出さない）
        if self.choosing or self.entry.focus_get() is not self.entry:
            self.hide()
            return
        matches = suggest_tasks(self.counts, self.text.get(), MAX_SUGGESTIONS)
        self.hide()
        if matches:
            self.show(matches)

    def show(self, matches: list[tuple[str, int]]) -> None:
        # 画面の部品の上に重ねるため、ウィンドウに直接置く（画面を切り替えると、画面と一緒に消える）
        window = self.entry.winfo_toplevel()
        self.box = box = tk.Frame(window, bg=C.bg, highlightthickness=1, highlightbackground=C.border)
        for task, count in matches:
            row = tk.Frame(box, bg=C.bg, cursor="hand2")
            row.pack(fill="x")
            labels = [
                make_label(row, task, size=11, anchor="w"),
                make_label(row, f"{count}回", size=10, color=C.muted),
            ]
            labels[0].pack(side="left", fill="x", expand=True, padx=(px(10), 0), pady=px(4))
            labels[1].pack(side="right", padx=(px(8), px(10)))
            for widget in (row, *labels):
                widget.bind("<Button-1>", partial(self.on_click, task))
                widget.bind("<Enter>", partial(self.paint, row, C.subtle))
                widget.bind("<Leave>", partial(self.paint, row, C.bg))
        x = self.entry.winfo_rootx() - window.winfo_rootx()
        y = self.entry.winfo_rooty() - window.winfo_rooty() + self.entry.winfo_height() + px(2)
        box.place(x=x, y=y, width=self.entry.winfo_width())
        box.lift()

    @staticmethod
    def paint(row: tk.Frame, color: str, event: tk.Event | None = None) -> None:
        """マウスを乗せた候補を淡く塗る"""
        row.configure(bg=color)
        for widget in row.winfo_children():
            widget.configure({"bg": color})

    def on_click(self, task: str, event: tk.Event) -> None:
        self.choose(task)

    def choose(self, task: str) -> None:
        self.choosing = True  # 選んだ名前を含むほかの名前（「英語」→「英語の勉強」）が、また出ないように
        self.text.set(task)
        self.choosing = False
        self.entry.icursor("end")
        self.entry.focus_set()

    def hide(self) -> None:
        if self.box is not None:
            self.box.destroy()
            self.box = None

    def on_escape(self, event: tk.Event) -> str | None:
        """候補が出ていれば消すだけにする（画面の「戻る」は動かさない）"""
        if self.box is None:
            return None
        self.hide()
        return "break"
