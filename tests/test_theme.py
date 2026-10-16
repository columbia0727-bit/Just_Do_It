from functools import partial
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit.ui import theme  # noqa: E402

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$|^[a-zA-Z]+$")


class ResolveModeTest(unittest.TestCase):
    def test_light_and_dark_are_used_as_is(self):
        with mock.patch.object(theme, "system_prefers_dark", return_value=True):
            self.assertEqual(theme.resolve_mode("light"), "light")
        with mock.patch.object(theme, "system_prefers_dark", return_value=False):
            self.assertEqual(theme.resolve_mode("dark"), "dark")

    def test_system_follows_the_os(self):
        with mock.patch.object(theme, "system_prefers_dark", return_value=True):
            self.assertEqual(theme.resolve_mode("system"), "dark")
        with mock.patch.object(theme, "system_prefers_dark", return_value=False):
            self.assertEqual(theme.resolve_mode("system"), "light")

    def test_palettes_define_every_color(self):
        # ライトとダークで、同じ名前の色がすべて決まっている（どちらかだけ足し忘れると表示が崩れる）
        for palette in (theme.LIGHT, theme.DARK):
            for name, value in vars(palette).items():
                self.assertRegex(value, r"^#[0-9a-f]{6}$", name)


class ThemeColorsTest(unittest.TestCase):
    """ライト・ダークどちらでも、部品の色がすべて今の配色から来ていること

    clam テーマや Tk の初期値の色（フォーカス中は白い文字など）が残っていると、
    背景と同じ色の文字になって読めなくなることがあるため。
    """

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(setattr, theme, "_current_mode", None)

    def palette_colors(self) -> set[str]:
        return {value.lower() for value in vars(theme.C).values()}

    def assert_colors_from_palette(self, where: str, values) -> None:
        palette = self.palette_colors()
        for value in values:
            text = str(value).lower()
            if COLOR_PATTERN.match(text) and text not in ("", "flat", "groove", "solid", "raised", "sunken", "ridge"):
                self.assertIn(text, palette, f"{where} に配色にない色 {value} が残っている")

    def test_ttk_styles_use_only_palette_colors(self):
        style = ttk.Style(self.root)
        for mode in ("light", "dark"):
            theme.apply_theme(self.root, mode)
            for name in (".",) + theme.TTK_STYLES:
                for option, value in style.configure(name).items():
                    if "color" in option or "background" in option or "foreground" in option:
                        self.assert_colors_from_palette(f"[{mode}] {name}.{option}", [value])
                for option, states in style.map(name).items():
                    self.assert_colors_from_palette(f"[{mode}] {name}.map.{option}", [s[-1] for s in states])

    def contrast(self, color1: str, color2: str) -> float:
        """2つの色のコントラスト比（WCAG の計算式。1〜21、読みやすい文字は 4.5 以上）"""

        def luminance(color: str) -> float:
            channels = [c / 65535 for c in self.root.winfo_rgb(color)]
            linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        lighter, darker = sorted((luminance(color1), luminance(color2)), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    def test_text_is_readable_in_every_state(self):
        """ライト・ダークそれぞれ、記録一覧の表の文字が、どの状態でも背景に対して読める濃さであること"""
        style = ttk.Style(self.root)
        cases = [
            # (部品, 状態, 文字の色の項目, 背景の色の項目)
            ("Treeview", [], "foreground", "background"),
            ("Treeview", ["selected"], "foreground", "background"),
            ("Treeview.Heading", [], "foreground", "background"),
            ("Treeview.Heading", ["active"], "foreground", "background"),
        ]
        for mode in ("light", "dark"):
            theme.apply_theme(self.root, mode)
            for name, state, fg_option, bg_option in cases:
                fg = style.lookup(name, fg_option, state)
                bg = style.lookup(name, bg_option, state)
                minimum = 3.0 if name == "Treeview.Heading" else 4.5  # 見出しは補足の色なので少しゆるめる
                self.assertGreaterEqual(
                    self.contrast(fg, bg), minimum, f"[{mode}] {name} {state}: 文字 {fg} / 背景 {bg} が読みにくい"
                )

    def test_palette_pairs_are_readable(self):
        """ボタン・入力欄・候補など、文字と背景の組み合わせが読める濃さであること"""
        pairs = [
            ("text", "bg", 4.5),
            ("text", "surface", 4.5),
            ("text", "subtle", 4.5),  # 候補・選択中のタブ
            ("text", "subtle_hover", 4.5),
            ("on_accent", "accent", 4.5),  # 目立たせるボタン
            ("on_accent", "accent_hover", 4.5),
            ("muted", "bg", 3.0),  # 補足の文字
            ("error", "bg", 4.5),
        ]
        for name, palette in (("light", theme.LIGHT), ("dark", theme.DARK)):
            for fg, bg, minimum in pairs:
                ratio = self.contrast(getattr(palette, fg), getattr(palette, bg))
                self.assertGreaterEqual(ratio, minimum, f"[{name}] {fg} / {bg} のコントラスト {ratio:.1f}")

    def test_select_shows_and_changes_choice(self):
        chosen = []
        select = theme.make_select(self.root, ["15分", "25分", "50分"], 1, chosen.append)
        self.assertEqual((select.current(), select.get()), (1, "25分"))
        self.assertIn("25分", select.text)

        select.choose(2)  # メニューで「50分」を選んだとき
        self.assertEqual(chosen, [2])
        self.assertEqual(select.get(), "50分")
        self.assertIn("50分", select.text)

        select.current(0)  # 表示だけ戻す（保存に失敗したときなど）。on_select は呼ばない
        self.assertEqual((select.get(), chosen), ("15分", [2]))

    def test_buttons_and_links_work_with_keyboard(self):
        """Tab キーで選べて、Enter・スペースで1回だけ押せる（画面全体に登録した Enter は動かない）"""
        self.root.deiconify()
        screen_keys = []
        self.root.bind("<Return>", lambda event: screen_keys.append("Return"))
        for make in (theme.make_button, theme.make_link):
            pressed = []
            widget = make(self.root, "x", partial(pressed.append, 1))
            widget.pack()
            self.assertEqual(int(widget.cget("takefocus")), 1)
            widget.focus_force()
            self.root.update()
            widget.event_generate("<Return>")
            widget.event_generate("<space>")
            self.assertEqual(pressed, [1, 1], make.__name__)
        self.assertEqual(screen_keys, [])
        # 押すためのものではない（選んでいるタブなど）は、Tab キーで選ばない
        self.assertIn(str(theme.PillButton(self.root, "x", None, kind="tab_active").cget("takefocus")), ("", "0"))

    def test_widgets_use_only_palette_colors(self):
        visible_options = (
            "background", "foreground", "insertbackground", "selectbackground", "selectforeground",
            "selectcolor", "activebackground", "activeforeground", "highlightcolor", "highlightbackground",
        )
        for mode in ("light", "dark"):
            theme.apply_theme(self.root, mode)
            frame = tk.Frame(self.root, bg=theme.C.bg)
            widgets = {
                "label": theme.make_label(frame, "x"),
                "entry": theme.make_entry(frame),
                "checkbox": theme.make_checkbox(frame, "x", True, lambda checked: None),
                "button": theme.make_button(frame, "x", lambda: None),
                "select": theme.make_select(frame, ["25分", "50分"], 0, lambda index: None),
            }
            for name, widget in widgets.items():
                values = [
                    widget.cget(option)
                    for option in visible_options
                    if option in widget.keys()
                    # 枠線の色は、枠線を表示しているときだけ確かめる
                    and not (option.startswith("highlight") and int(widget.cget("highlightthickness")) == 0)
                    # Label の active 系の色は、ボタンとして使わない限り表示されない
                    and not (option.startswith("active") and isinstance(widget, tk.Label))
                ]
                self.assert_colors_from_palette(f"[{mode}] {name}", values)
            frame.destroy()


if __name__ == "__main__":
    unittest.main()
