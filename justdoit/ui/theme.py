"""画面の配色（ライト / ダーク）・フォントと、共通の部品（ボタン・入力欄・進捗リングなど）

色は各画面に直接書かず、必ず C（今の配色）から読む。apply_theme() で C の中身を
ライト用・ダーク用に入れ替え、画面を作り直すと新しい色で表示される。
"""

from collections.abc import Callable
from dataclasses import dataclass, fields
from functools import partial
import math
import platform
import subprocess
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


# ==========================================
# 配色
# ==========================================
@dataclass
class Palette:
    """作業の邪魔をしないよう、色はアクセント1色に絞る"""

    bg: str  # 画面の背景
    surface: str  # 入力欄・表の背景
    text: str
    muted: str  # 補足の文字
    border: str
    subtle: str  # 目立たないボタン・選択中のタブ
    subtle_hover: str
    accent: str
    accent_hover: str
    on_accent: str  # accent の上の文字
    error: str
    ring_track: str  # 進捗リングの残りの部分


LIGHT = Palette(
    bg="#f7f7f5",
    surface="#ffffff",
    text="#222222",
    muted="#8a8a86",
    border="#dcdcd8",
    subtle="#ebebe7",
    subtle_hover="#e0e0db",
    accent="#2f6f62",
    accent_hover="#265a50",
    on_accent="#ffffff",
    error="#b3261e",
    ring_track="#e4e4e0",
)

DARK = Palette(
    bg="#17191c",
    surface="#202328",
    text="#ececea",
    muted="#8f949b",
    border="#363a42",
    subtle="#262a30",
    subtle_hover="#30353c",
    accent="#4fb393",
    accent_hover="#63c4a4",
    on_accent="#0b2a22",
    error="#f2827a",
    ring_track="#2a2f36",
)

APPEARANCE_CHOICES = [("system", "デバイスに合わせる"), ("light", "ライト"), ("dark", "ダーク")]

# 今の配色（apply_theme で中身を入れ替える）
C = Palette(**{f.name: getattr(LIGHT, f.name) for f in fields(Palette)})
_current_mode: str | None = None
# Windows の表示倍率（app が起動時に設定する）
_scale = 1.0


def set_scale(scale: float) -> None:
    global _scale
    _scale = scale


def px(value: float) -> int:
    """100% 表示のときのピクセル数を、今の表示倍率に合わせて変換する"""
    return round(value * _scale)


def system_prefers_dark(root: tk.Misc | None = None) -> bool:
    """OS がダークモードかどうか（調べられなければライト扱い）

    画面を切り替えるたびに呼ぶので、速く調べられる方法を使う。
    """
    # OS ごとの分岐は sys.platform で書く（mypy が OS ごとに見分け、ほかの OS にない機能をエラーにしないように）
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            with key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            # Tk に聞けばすぐにわかる（別のプログラムを起動しないので、画面の切り替えが遅れない）
            if root is not None:
                try:
                    return root.tk.call("::tk::unsupported::MacWindowStyle", "isdark", root) in (1, "1", True)
                except tk.TclError:
                    pass  # 古い Tk には無いので、下の方法で調べる
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2
            )
            return "Dark" in result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def resolve_mode(appearance: str, root: tk.Misc | None = None) -> str:
    """設定（"system" / "light" / "dark"）から、実際に使う "light" / "dark" を決める"""
    if appearance in ("light", "dark"):
        return appearance
    return "dark" if system_prefers_dark(root) else "light"


def apply_theme(root: tk.Tk, appearance: str) -> bool:
    """配色を切り替える。変わったら True（呼び出し側で画面を作り直す）"""
    global _current_mode
    mode = resolve_mode(appearance, root)
    if mode == _current_mode:
        return False
    _current_mode = mode
    palette = DARK if mode == "dark" else LIGHT
    for field in fields(Palette):
        setattr(C, field.name, getattr(palette, field.name))

    root.configure(bg=C.bg)
    _style_ttk(root)
    _set_title_bar_dark(root, mode == "dark")
    return True


TTK_STYLES = ("Treeview", "Treeview.Heading", "TScrollbar", "Vertical.TScrollbar")


def _style_ttk(root: tk.Tk) -> None:
    """ttk の部品（記録一覧の表・スクロールバー）を今の配色にする

    clam テーマには「フォーカス中は白い文字」のような状態ごとの色が最初から決まっているため、
    configure（通常の色）だけでなく map（状態ごとの色）も、使う状態をすべて今の配色で指定し直す。
    （map は指定した項目だけが置き換わり、指定しなかった項目は clam の色のまま残る）
    """
    style = ttk.Style(root)
    # 標準の Windows テーマは色を変えられないため、色を細かく指定できる clam を使う
    style.theme_use("clam")
    common = {"bordercolor": C.border, "lightcolor": C.border, "darkcolor": C.border}

    # すべての ttk 部品の土台
    style.configure(
        ".",
        background=C.bg,
        foreground=C.text,
        troughcolor=C.surface,
        focuscolor=C.accent,
        selectbackground=C.accent,
        selectforeground=C.on_accent,
        insertcolor=C.text,
        **common,
    )
    style.map(
        ".",
        background=[("disabled", C.subtle), ("active", C.subtle_hover)],
        foreground=[("disabled", C.muted)],
        selectbackground=[("!focus", C.subtle)],
        selectforeground=[("!focus", C.text)],
    )

    style.configure(
        "Treeview", background=C.surface, fieldbackground=C.surface, foreground=C.text, borderwidth=0, **common
    )
    style.map(
        "Treeview",
        background=[("disabled", C.subtle), ("selected", C.accent)],
        foreground=[("disabled", C.muted), ("selected", C.on_accent)],
        bordercolor=[("focus", C.border)],
    )
    style.configure("Treeview.Heading", background=C.bg, foreground=C.muted, relief="flat", **common)
    style.map("Treeview.Heading", background=[("active", C.subtle)], foreground=[("active", C.text)])

    for scrollbar in ("TScrollbar", "Vertical.TScrollbar"):
        style.configure(scrollbar, background=C.subtle, troughcolor=C.surface, arrowcolor=C.muted, **common)
        style.map(
            scrollbar,
            background=[("disabled", C.surface), ("pressed", C.subtle_hover), ("active", C.subtle_hover)],
            arrowcolor=[("disabled", C.border)],
        )


def _set_title_bar_dark(root: tk.Tk, dark: bool) -> None:
    """Windows 10/11 のタイトルバーも暗くする（できない環境では何もしない）"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        # 20: DWMWA_USE_IMMERSIVE_DARK_MODE（古い Windows 10 では 19）
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4) == 0:
                break
    except (AttributeError, OSError):
        pass


# ==========================================
# フォント
# ==========================================
UI_FONT_FAMILY = {
    "Darwin": "Hiragino Sans",
    "Windows": "Yu Gothic UI",
}.get(platform.system(), "Noto Sans CJK JP")


def ui_font(size: int = 12, bold: bool = False) -> tuple:
    return (UI_FONT_FAMILY, size, "bold") if bold else (UI_FONT_FAMILY, size)


# ==========================================
# なめらかな角丸・リングの画像（Tk の Canvas は縁がギザギザになるため、
# PIL で4倍の大きさに描いてから縮小する）
# ==========================================
SUPERSAMPLE = 4


def _to_photo(image: Image.Image, size: tuple[int, int]) -> ImageTk.PhotoImage:
    """縮小して Tk の画像にする（半透明の縁は Tk でうまく混ざらないので、背景色ごと描いた不透明な画像にする）"""
    return ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS))


def rounded_rect_image(
    width: int,
    height: int,
    radius: int,
    fill: str,
    background: str,
    outline: str | None = None,
    outline_width: int = 1,
) -> ImageTk.PhotoImage:
    s = SUPERSAMPLE
    image = Image.new("RGB", (width * s, height * s), background)
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, width * s - 1, height * s - 1),
        radius=radius * s,
        fill=fill,
        outline=outline,
        width=outline_width * s if outline else 0,
    )
    return _to_photo(image, (width, height))


def ring_image(size: int, progress: float, thickness: int) -> ImageTk.PhotoImage:
    """残り時間の割合 progress（1 → 0）を、12時の位置から時計回りの円弧で描く"""
    s = SUPERSAMPLE
    big, line = size * s, thickness * s
    image = Image.new("RGB", (big, big), C.bg)
    draw = ImageDraw.Draw(image)
    box = (line // 2, line // 2, big - line // 2 - 1, big - line // 2 - 1)
    draw.ellipse(box, outline=C.ring_track, width=line)
    if progress > 0:
        end = -90 + 360 * progress
        draw.arc(box, start=-90, end=end, fill=C.accent, width=line)
        # 線の両端を丸くする
        center, radius = big / 2, (big - line) / 2
        for angle in (-90, end):
            x = center + radius * math.cos(math.radians(angle))
            y = center + radius * math.sin(math.radians(angle))
            draw.ellipse((x - line / 2, y - line / 2, x + line / 2, y + line / 2), fill=C.accent)
    return _to_photo(image, (size, size))


class PillButton(tk.Label):
    """角の丸いボタン。width を省略すると、pack(fill="x") などで広げた幅に合わせて描き直す

    kind: "primary"（塗りつぶし・1画面に1つ）/ "secondary"（枠線）/ "chip"（小さな候補）/
          "tab"・"tab_active"（切り替えタブ）/ "select"（選択欄。角丸を小さくして入力欄に似せる）
    マウスを乗せたときはカーソルを変えず、ボタンの色だけを変える（指の形のカーソルは Mac で不自然に見えるため）
    Tab キーで選ぶと、文字色の枠で囲んで示し、Enter・スペースキーで押せる
    """

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], object] | None,
        kind: str = "secondary",
        width: int | None = None,
    ):
        size, height, bold = {
            "primary": (12, 42, True),
            "secondary": (12, 42, False),
            "chip": (10, 28, False),
            "tab": (10, 28, False),
            "tab_active": (10, 28, True),
            "select": (11, 32, False),
        }[kind]
        self.fill, self.hover, self.outline, fg = {
            "primary": (C.accent, C.accent_hover, None, C.on_accent),
            "secondary": (C.bg, C.subtle, C.border, C.text),
            "chip": (C.subtle, C.subtle_hover, None, C.text),
            "tab": (C.bg, C.subtle, None, C.muted),
            "tab_active": (C.subtle, C.subtle, None, C.text),
            "select": (C.surface, C.subtle, C.border, C.text),
        }[kind]
        super().__init__(
            parent,
            text=text,
            font=ui_font(size, bold),
            fg=fg,
            bg=parent["bg"],
            compound="center",
            # 余白があると画像より広がり、幅に合わせて描き直すたびに広がり続けるので 0 にする
            bd=0,
            padx=0,
            pady=0,
            highlightthickness=0,
        )
        self.height = px(height)
        self.radius = px(8) if kind == "select" else self.height // 2
        self.images: dict[tuple[int, bool, bool], ImageTk.PhotoImage] = {}
        self.hovering = False
        self.focused = False
        if width is None and kind in ("chip", "tab", "tab_active"):
            # 文字の幅に合わせる
            width = round(tkfont.Font(font=self["font"]).measure(text) / _scale) + 28
        self.fixed_width = px(width) if width else None
        self.draw(self.fixed_width or px(60))

        if command:
            self.bind("<Button-1>", lambda event: command())
            self.bind("<Enter>", lambda event: self.set_hover(True))
            self.bind("<Leave>", lambda event: self.set_hover(False))
            self.config(takefocus=1)
            bind_activate(self, command)
            self.bind("<FocusIn>", lambda event: self.set_focus(True))
            self.bind("<FocusOut>", lambda event: self.set_focus(False))
        if not self.fixed_width:
            self.bind("<Configure>", lambda event: self.draw(event.width))

    def draw(self, width: int) -> None:
        self.current_width = width
        key = (width, self.hovering, self.focused)
        if key not in self.images:
            fill = self.hover if self.hovering else self.fill
            # 背景色は "SystemButtonFace" のような名前のこともあるので、#rrggbb にしてから描く
            red, green, blue = (value // 256 for value in self.winfo_rgb(self["bg"]))
            background = f"#{red:02x}{green:02x}{blue:02x}"
            outline, outline_width = (C.text, 2) if self.focused else (self.outline, 1)
            self.images[key] = rounded_rect_image(
                width, self.height, self.radius, fill, background, outline=outline, outline_width=outline_width
            )
        self.config(image=self.images[key])

    def set_hover(self, hovering: bool) -> None:
        self.hovering = hovering
        self.draw(self.current_width)

    def set_focus(self, focused: bool) -> None:
        # 押したボタンで画面を切り替えると、消える途中で呼ばれることがある
        if self.winfo_exists():
            self.focused = focused
            self.draw(self.current_width)


def bind_activate(widget: tk.Widget, command: Callable[[], object]) -> None:
    """Tab キーで選んだ部品を、Enter・スペースキーで押せるようにする

    "break" を返して、画面全体に登録した同じキー（Enter で保存など）が続けて動かないようにする。
    """

    def activate(event: tk.Event) -> str:
        command()
        return "break"

    for sequence in ("<Return>", "<KP_Enter>", "<space>"):
        widget.bind(sequence, activate)


# ==========================================
# 部品
# ==========================================
def make_label(
    parent: tk.Widget, text: str = "", size: int = 12, color: str | None = None, bold: bool = False, **options
) -> tk.Label:
    return tk.Label(parent, text=text, font=ui_font(size, bold), fg=color or C.text, bg=parent["bg"], **options)


def make_button(
    parent: tk.Widget, text: str, command: Callable[[], object], primary: bool = False, width: int | None = None
) -> PillButton:
    """角の丸いボタン（primary は1画面に1つだけ）。width を省略すると広げた幅に合わせる"""
    return PillButton(parent, text, command, kind="primary" if primary else "secondary", width=width)


def make_back_button(parent: tk.Widget, command: Callable[[], object]) -> PillButton:
    """画面右上の「← 戻る」（文字だけだと見落としやすいので、小さなボタンにする）"""
    return PillButton(parent, "← 戻る", command, kind="chip")


def make_link(parent: tk.Widget, text: str, command: Callable[[], object], accent: bool = False) -> tk.Label:
    """目立たせたくない操作用の、文字だけのボタン（accent なら、気づいてほしいお知らせ用にアクセント色にする）"""
    color, hover = (C.accent, C.accent_hover) if accent else (C.muted, C.text)
    link = make_label(parent, text, size=10, color=color, takefocus=1)
    link.bind("<Button-1>", lambda event: command())
    link.bind("<Enter>", lambda event: link.config(fg=hover))
    link.bind("<Leave>", lambda event: link.config(fg=color))
    # Tab キーで選んだときは、下線を引いて示す
    def show_focus(focused: bool) -> None:
        if link.winfo_exists():
            link.config(fg=hover if focused else color, font=ui_font(10) + (("underline",) if focused else ()))

    link.bind("<FocusIn>", lambda event: show_focus(True))
    link.bind("<FocusOut>", lambda event: show_focus(False))
    bind_activate(link, command)
    return link


def make_entry(parent: tk.Widget, **options) -> tk.Entry:
    return tk.Entry(
        parent,
        font=ui_font(12),
        relief="flat",
        bg=C.surface,
        fg=C.text,
        insertbackground=C.text,
        selectbackground=C.accent,
        selectforeground=C.on_accent,
        highlightthickness=1,
        highlightbackground=C.border,
        highlightcolor=C.accent,
        **options,
    )


class SelectButton(PillButton):
    """選択肢から1つ選ぶ欄。押すと OS 標準のメニューで選択肢を出し、選ばれると on_select(選んだ番号) を呼ぶ

    ttk.Combobox は Mac で描画が遅れて、画面を切り替えたときに選択欄だけ後から表示されるため、
    ほかのボタンと同じ作り（角丸の画像のラベル）にしている。
    """

    def __init__(self, parent: tk.Widget, values: list[str], selected: int, on_select: Callable[[int], object]):
        self.values = values
        self.index = selected
        self.on_select = on_select
        # いちばん長い選択肢が入る幅（▾ と左右の余白のぶんを足す）
        font = tkfont.Font(font=ui_font(11))
        width = round(max(font.measure(value) for value in values) / _scale) + 48
        super().__init__(parent, self.label_text(), self.open_menu, kind="select", width=width)

    def label_text(self) -> str:
        return f"{self.values[self.index]}   ▾"

    def open_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, font=ui_font(11))
        selected = tk.IntVar(value=self.index)
        for index, value in enumerate(self.values):
            menu.add_radiobutton(
                label=value, variable=selected, value=index, command=partial(self.choose, index)
            )
        try:
            # 選択欄のすぐ下に開く
            menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())
        finally:
            menu.grab_release()

    def choose(self, index: int) -> None:
        self.current(index)
        self.on_select(index)

    def current(self, index: int | None = None) -> int:
        """選んでいる番号を返す。index を渡すと、その選択肢を選んだ表示にする（on_select は呼ばない）"""
        if index is not None:
            self.index = index
            self.config(text=self.label_text())
        return self.index

    def get(self) -> str:
        return self.values[self.index]


def make_select(
    parent: tk.Widget, values: list[str], selected: int, on_select: Callable[[int], object]
) -> SelectButton:
    """選択肢から1つ選ぶ欄。選ばれると on_select(選んだ番号) を呼ぶ"""
    return SelectButton(parent, values, selected, on_select)


def make_checkbox(parent: tk.Widget, text: str, checked: bool, on_change: Callable[[bool], object]) -> tk.Checkbutton:
    """チェックボックス。切り替えると on_change(チェックの有無) を呼ぶ"""
    var = tk.BooleanVar(value=checked)
    box = tk.Checkbutton(
        parent,
        text=text,
        variable=var,
        command=lambda: on_change(var.get()),
        font=ui_font(11),
        fg=C.text,
        bg=parent["bg"],
        activebackground=parent["bg"],
        activeforeground=C.text,
        selectcolor=C.surface,
        anchor="w",
        bd=0,
        # Tab キーで選んだときだけ、文字色の枠で囲む（スペースキーで切り替えられる）
        highlightthickness=1,
        highlightcolor=C.text,
        highlightbackground=parent["bg"],
    )
    # var は command の中で使っているので、ボタンがある間は消えない
    return box


def make_chips(
    parent: tk.Widget, texts: list[str], on_click: Callable[[str], object], max_width: int, max_rows: int = 2
) -> tk.Frame:
    """押すと on_click(文字) を呼ぶ小さなボタンを、幅に収まるよう折り返して並べる（入りきらない分は出さない）"""
    chips = tk.Frame(parent, bg=parent["bg"])
    rows: list[tk.Frame] = []

    def new_row() -> tk.Frame:
        row = tk.Frame(chips, bg=parent["bg"])
        row.pack(anchor="w", pady=(0, px(4)))
        rows.append(row)
        return row

    def add_chip(row: tk.Frame, text: str) -> PillButton:
        label = text if len(text) <= 10 else text[:9] + "…"
        chip = PillButton(row, label, lambda: on_click(text), kind="chip")
        chip.pack(side="left", padx=(0, px(6)))
        return chip

    row = new_row()
    for text in texts:
        chip = add_chip(row, text)
        row.update_idletasks()
        if row.winfo_reqwidth() > max_width and len(row.winfo_children()) > 1:
            # 幅からはみ出したら次の行へ
            chip.destroy()
            if len(rows) == max_rows:
                break
            row = new_row()
            add_chip(row, text)
    return chips


def make_tabs(
    parent: tk.Widget, options: list[tuple[str, str]], selected: str, on_select: Callable[[str], object]
) -> tk.Frame:
    """「週｜月｜年」のような切り替えボタン（選んでいるものだけ淡く塗る）

    options は (キー, 表示) のリスト。選ばれると on_select(キー) を呼ぶ。
    """
    tabs = tk.Frame(parent, bg=parent["bg"])
    for key, text in options:
        active = key == selected
        PillButton(
            tabs, text, None if active else partial(on_select, key), kind="tab_active" if active else "tab"
        ).pack(side="left", padx=(0, px(2)))
    return tabs
