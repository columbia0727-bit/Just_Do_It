"""日付を選ぶ欄（押すとカレンダーが開き、日付を押すと選べる）

Tkinter には標準のカレンダーがなく、追加のライブラリは配色（ダークモード）がほかの部品とそろわないため、
ほかのボタンと同じ作り（角丸の画像のラベル）で作っている。
カレンダーは別のウィンドウではなく、同じウィンドウの上に重ねて表示する（Mac で別ウィンドウのフォーカスが不安定なため）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from functools import partial
import tkinter as tk

from PIL import ImageTk

from justdoit.records import day_label, month_weeks
from justdoit.ui.theme import C, PillButton, make_label, px, rounded_rect_image, text_width, ui_font

DAY_SIZE = 32  # カレンダーの1日分の大きさ
WEEKDAY_HEADINGS = "月火水木金土日"


class DatePicker(PillButton):
    """日付を選ぶ欄。first〜last の日付だけを選べる。選ぶと on_select(日付) を呼ぶ"""

    def __init__(
        self,
        parent: tk.Widget,
        selected: date,
        first: date,
        last: date,
        on_select: Callable[[date], object] | None = None,
    ):
        self.selected = selected
        self.first = first
        self.last = last
        self.on_select = on_select
        self.popup: CalendarPopup | None = None
        # いちばん長い日付の表示が入る幅（▾ と左右の余白のぶんを足す）
        labels = [self.label_text(first + timedelta(days=i)) for i in range((last - first).days + 1)]
        super().__init__(parent, self.label_text(selected), self.open, kind="select", width=text_width(labels, 11) + 48)

    def label_text(self, day: date) -> str:
        return f"{day_label(day, self.last)}   ▾"

    def get(self) -> date:
        return self.selected

    def open(self) -> None:
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = CalendarPopup(self)

    def choose(self, day: date) -> None:
        self.selected = day
        self.config(text=self.label_text(day))
        if self.on_select:
            self.on_select(day)


class CalendarPopup(tk.Frame):
    """DatePicker のすぐ下に重ねて出す、1か月分のカレンダー

    日付を押すか、矢印キーで動かして Enter で選ぶ。Esc・カレンダーの外を押すと閉じる。
    """

    def __init__(self, picker: DatePicker):
        self.picker = picker
        self.window = picker.winfo_toplevel()
        super().__init__(
            self.window, bg=C.surface, padx=px(8), pady=px(8), highlightthickness=1, highlightbackground=C.border
        )
        self.cursor = picker.selected  # キーボードで選んでいる日
        self.month = (picker.selected.year, picker.selected.month)
        self.images: dict[str, ImageTk.PhotoImage] = {}
        self.render()
        self.place_below(picker)

        # カレンダーの外を押したら閉じる（カレンダーを開いた欄自体を押したときも、開いたままにしない）
        self.click_binding = self.window.bind("<Button-1>", self.on_click_anywhere, add="+")
        self.bind("<Destroy>", self.on_destroy)
        for sequence, step in (("<Left>", -1), ("<Right>", 1), ("<Up>", -7), ("<Down>", 7)):
            self.bind(sequence, partial(self.move_cursor, step))
        for sequence in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(sequence, lambda event: self.choose(self.cursor))
        self.bind("<Escape>", lambda event: self.close())
        self.bind("<FocusOut>", self.on_focus_out)
        self.focus_set()

    # ---------- 表示 ----------
    def render(self) -> None:
        """今の月のカレンダーを作り直す（月を切り替えたときも、ここで作り直す）"""
        for child in self.winfo_children():
            child.destroy()
        year, month = self.month

        header = tk.Frame(self, bg=C.surface)
        header.pack(fill="x", pady=(0, px(6)))
        first, last = self.picker.first, self.picker.last
        can_go_back = (year, month) > (first.year, first.month)
        can_go_next = (year, month) < (last.year, last.month)
        self.month_button(header, "‹", -1, can_go_back).pack(side="left")
        self.month_button(header, "›", 1, can_go_next).pack(side="right")
        make_label(header, f"{year}年{month}月", size=11, bold=True).pack(side="left", expand=True)

        days = tk.Frame(self, bg=C.surface)
        days.pack()
        for column, name in enumerate(WEEKDAY_HEADINGS):
            make_label(days, name, size=9, color=C.muted).grid(row=0, column=column, pady=(0, px(2)))
        for row, week in enumerate(month_weeks(year, month), start=1):
            for column, day in enumerate(week):
                self.day_cell(days, day).grid(row=row, column=column)

    def month_button(self, parent: tk.Widget, text: str, step: int, enabled: bool) -> PillButton:
        if not enabled:
            return PillButton(parent, text, None, kind="chip_disabled", width=28)
        return PillButton(parent, text, lambda: self.change_month(step), kind="chip", width=28)

    def day_cell(self, parent: tk.Widget, day: date | None) -> tk.Label:
        cell = tk.Label(parent, bg=C.surface, bd=0, padx=0, pady=0, compound="center", font=ui_font(10))
        if day is None:
            cell.config(image=self.image("blank"))
            return cell
        selectable = self.picker.first <= day <= self.picker.last
        if day == self.picker.selected:
            state, color = "selected", C.on_accent
        elif day == self.cursor:
            state, color = "cursor", C.text
        else:
            state, color = "blank", C.text if selectable else C.border
        cell.config(
            text=str(day.day),
            image=self.image(state),
            fg=color,
            font=ui_font(10, bold=day == self.picker.last),  # 今日は太字
        )
        if selectable:
            cell.bind("<Button-1>", lambda event: self.choose(day))
            if state == "blank":
                cell.bind("<Enter>", lambda event: cell.config(image=self.image("hover")))
                cell.bind("<Leave>", lambda event: cell.config(image=self.image("blank")))
        return cell

    def image(self, state: str) -> ImageTk.PhotoImage:
        """1日分の丸い背景（選んでいる日は塗りつぶし、キーボードで選んでいる日は枠線）"""
        if state not in self.images:
            fill, outline = {
                "blank": (C.surface, None),
                "hover": (C.subtle, None),
                "selected": (C.accent, None),
                "cursor": (C.surface, C.text),
            }[state]
            size = px(DAY_SIZE)
            self.images[state] = rounded_rect_image(size, size, size // 2, fill, C.surface, outline=outline)
        return self.images[state]

    def place_below(self, picker: DatePicker) -> None:
        """欄のすぐ下に出す（ウィンドウからはみ出すときは、収まる位置までずらす）"""
        self.update_idletasks()
        x = picker.winfo_rootx() - self.window.winfo_rootx()
        y = picker.winfo_rooty() - self.window.winfo_rooty() + picker.winfo_height() + px(4)
        x = max(0, min(x, self.window.winfo_width() - self.winfo_reqwidth()))
        y = max(0, min(y, self.window.winfo_height() - self.winfo_reqheight()))
        self.place(x=x, y=y)
        self.lift()

    # ---------- 操作 ----------
    def change_month(self, step: int) -> None:
        year, month = self.month
        month += step
        self.month = (year + (month - 1) // 12, (month - 1) % 12 + 1)
        self.render()
        self.focus_set()

    def move_cursor(self, step: int, event: tk.Event | None = None) -> str:
        day = self.cursor + timedelta(days=step)
        if self.picker.first <= day <= self.picker.last:
            self.cursor = day
            self.month = (day.year, day.month)
            self.render()
        return "break"  # 画面全体に登録した ← → キー（振り返りの期間の切り替えなど）を動かさない

    def choose(self, day: date) -> str:
        self.picker.choose(day)
        self.close()
        return "break"  # 画面全体に登録した Enter（保存など）を動かさない

    def close(self) -> str:
        picker = self.picker
        self.destroy()
        if picker.winfo_exists():
            picker.focus_set()
        return "break"  # 画面全体に登録した Esc（前の画面に戻る）を動かさない

    def contains(self, widget: object) -> bool:
        """widget がこのカレンダー自身か、その中の部品か"""
        return str(widget) == str(self) or str(widget).startswith(str(self) + ".")

    def on_click_anywhere(self, event: tk.Event) -> None:
        if self.winfo_exists() and not self.contains(event.widget) and event.widget is not self.picker:
            self.destroy()

    def on_focus_out(self, event: tk.Event) -> None:
        # Tab キーなどで、ほかの入力欄に移ったら閉じる（カレンダーの中の日付を押しても、フォーカスは動かない）
        focused = self.focus_get()
        if focused is not None and not self.contains(focused) and self.winfo_exists():
            self.destroy()

    def on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self.window.unbind("<Button-1>", self.click_binding)
