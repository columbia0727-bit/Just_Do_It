"""画面の配色（ライト / ダーク）・フォントと、共通の部品（ボタン・入力欄・進捗リングなど）

色は各画面に直接書かず、必ず C（今の配色）から読む。apply_theme() で C の中身を
ライト用・ダーク用に入れ替え、画面を作り直すと新しい色で表示される。
"""

from dataclasses import dataclass, fields
import math
import platform
import subprocess
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable

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


def system_prefers_dark() -> bool:
    """OS がダークモードかどうか（調べられなければライト扱い）"""
    try:
        system = platform.system()
        if system == "Windows":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            with key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if system == "Darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2
            )
            return "Dark" in result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def resolve_mode(appearance: str) -> str:
    """設定（"system" / "light" / "dark"）から、実際に使う "light" / "dark" を決める"""
    if appearance in ("light", "dark"):
        return appearance
    return "dark" if system_prefers_dark() else "light"


def apply_theme(root: tk.Tk, appearance: str) -> bool:
    """配色を切り替える。変わったら True（呼び出し側で画面を作り直す）"""
    global _current_mode
    mode = resolve_mode(appearance)
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


TTK_STYLES = ("TCombobox", "Treeview", "Treeview.Heading", "TScrollbar", "Vertical.TScrollbar")


def _style_ttk(root: tk.Tk) -> None:
    """ttk の部品（選択欄・表・スクロールバー）を今の配色にする

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
        "TCombobox",
        fieldbackground=C.surface,
        background=C.surface,
        foreground=C.text,
        arrowcolor=C.muted,
        selectbackground=C.surface,
        selectforeground=C.text,
        padding=(px(6), px(3)),
        **common,
    )
    style.map(
        "TCombobox",
        # 選んだあともフォーカスが残るので、フォーカス中も普段と同じ色にする
        foreground=[("disabled", C.muted), ("readonly", "focus", C.text), ("readonly", C.text)],
        fieldbackground=[("readonly", "focus", C.surface), ("readonly", C.surface)],
        background=[("active", C.subtle), ("pressed", C.subtle), ("readonly", C.surface)],
        selectbackground=[("focus", C.surface), ("!focus", C.surface)],
        selectforeground=[("focus", C.text), ("!focus", C.text)],
        bordercolor=[("focus", C.accent)],
        lightcolor=[("focus", C.accent)],
        arrowcolor=[("disabled", C.border)],
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
    # 選択欄を開いたときの一覧（ttk ではなく tk の Listbox なので option で指定する）
    for option, value in [
        ("background", C.surface),
        ("foreground", C.text),
        ("selectBackground", C.accent),
        ("selectForeground", C.on_accent),
        ("font", ui_font(11)),
    ]:
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    # 一覧の外枠（初期値は黒っぽい線）
    root.option_add("*TCombobox*Listbox.highlightThickness", 0)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)


def _set_title_bar_dark(root: tk.Tk, dark: bool) -> None:
    """Windows 10/11 のタイトルバーも暗くする（できない環境では何もしない）"""
    if platform.system() != "Windows":
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
    return ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))


def rounded_rect_image(
    width: int, height: int, radius: int, fill: str, background: str, outline: str | None = None
) -> ImageTk.PhotoImage:
    s = SUPERSAMPLE
    image = Image.new("RGB", (width * s, height * s), background)
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, width * s - 1, height * s - 1),
        radius=radius * s,
        fill=fill,
        outline=outline,
        width=s if outline else 0,
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
          "tab"・"tab_active"（切り替えタブ）
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
        }[kind]
        self.fill, self.hover, self.outline, fg = {
            "primary": (C.accent, C.accent_hover, None, C.on_accent),
            "secondary": (C.bg, C.subtle, C.border, C.text),
            "chip": (C.subtle, C.subtle_hover, None, C.text),
            "tab": (C.bg, C.subtle, None, C.muted),
            "tab_active": (C.subtle, C.subtle, None, C.text),
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
            cursor="hand2" if command else "arrow",
        )
        self.height = px(height)
        self.images: dict[tuple[int, bool], ImageTk.PhotoImage] = {}
        self.hovering = False
        if width is None and kind in ("chip", "tab", "tab_active"):
            # 文字の幅に合わせる
            width = round(tkfont.Font(font=self["font"]).measure(text) / _scale) + 28
        self.fixed_width = px(width) if width else None
        self.draw(self.fixed_width or px(60))

        if command:
            self.bind("<Button-1>", lambda event: command())
            self.bind("<Enter>", lambda event: self.set_hover(True))
            self.bind("<Leave>", lambda event: self.set_hover(False))
        if not self.fixed_width:
            self.bind("<Configure>", lambda event: self.draw(event.width))

    def draw(self, width: int) -> None:
        self.current_width = width
        key = (width, self.hovering)
        if key not in self.images:
            fill = self.hover if self.hovering else self.fill
            self.images[key] = rounded_rect_image(
                width, self.height, self.height // 2, fill, background=self["bg"], outline=self.outline
            )
        self.config(image=self.images[key])

    def set_hover(self, hovering: bool) -> None:
        self.hovering = hovering
        self.draw(self.current_width)


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


def make_link(parent: tk.Widget, text: str, command: Callable[[], object]) -> tk.Label:
    """目立たせたくない操作用の、文字だけのボタン"""
    link = make_label(parent, text, size=10, color=C.muted, cursor="hand2")
    link.bind("<Button-1>", lambda event: command())
    link.bind("<Enter>", lambda event: link.config(fg=C.text))
    link.bind("<Leave>", lambda event: link.config(fg=C.muted))
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


def make_select(
    parent: tk.Widget, values: list[str], selected: int, on_select: Callable[[int], object], width: int = 6
) -> ttk.Combobox:
    """選択肢から1つ選ぶ欄。選ばれると on_select(選んだ番号) を呼ぶ"""
    box = ttk.Combobox(parent, values=values, width=width, state="readonly", font=ui_font(11))
    box.current(selected)

    def selected_changed(event):
        box.selection_clear()  # 選んだ文字が反転表示のまま残らないようにする
        on_select(box.current())

    box.bind("<<ComboboxSelected>>", selected_changed)
    return box


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
        cursor="hand2",
        bd=0,
        highlightthickness=0,
    )
    box.var = var  # 変数が消えないよう、ウィジェットに持たせておく
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
            tabs, text, None if active else lambda k=key: on_select(k), kind="tab_active" if active else "tab"
        ).pack(side="left", padx=(0, px(2)))
    return tabs
