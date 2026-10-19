from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit.ui import confirm  # noqa: E402
from justdoit.ui.theme import PillButton  # noqa: E402

CHOICES = [confirm.Choice("やめてメニューに戻る", "quit"), confirm.Choice("タイマーを続ける", "continue", safe=True)]


class ConfirmTest(unittest.TestCase):
    """アプリの中に出す確認（confirm.ask）が、押したボタンの値を返すこと"""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        self.root.geometry("320x420")
        self.root.update()
        self.addCleanup(self.root.destroy)
        self.app = SimpleNamespace(root=self.root, px=lambda value: round(value), dialog_open=False)
        # 万一ボタンが押されないまま待ち続けても、テストが止まらないようにする
        self.root.after(5000, lambda: self.fail_safely())

    def fail_safely(self):
        self.timed_out = True
        for widget in self.root.winfo_children():
            widget.destroy()

    def card(self) -> tk.Frame:
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Frame)][-1]

    def press(self, label: str) -> None:
        def find(widget: tk.Misc) -> list[PillButton]:
            found = [widget] if isinstance(widget, PillButton) and widget.text == label else []
            for child in widget.winfo_children():
                found.extend(find(child))
            return found

        find(self.root)[0].event_generate("<Button-1>")

    def test_returns_pressed_choice(self):
        self.root.after(100, lambda: self.press("やめてメニューに戻る"))
        self.assertEqual(confirm.ask(self.app, "タイマーをやめますか？", "", CHOICES), "quit")
        self.assertFalse(self.app.dialog_open)

    def test_escape_chooses_safe(self):
        def press_escape():
            # キーは入力先（フォーカス）のある部品に届くので、テストのウィンドウでも入力先を移してから送る
            self.card().focus_force()
            self.root.update()
            self.card().event_generate("<Escape>")

        self.root.after(100, press_escape)
        self.assertEqual(confirm.ask(self.app, "タイマーをやめますか？", "", CHOICES), "continue")
        self.assertFalse(getattr(self, "timed_out", False))

    def test_screen_change_chooses_safe(self):
        # 確認を出している間にタイマーが終わり、画面が切り替わった（確認も消える）
        def switch_screen():
            for widget in self.root.winfo_children():
                widget.destroy()

        self.root.after(100, switch_screen)
        self.assertEqual(confirm.ask(self.app, "タイマーをやめますか？", "", CHOICES), "continue")

    def test_not_stacked(self):
        # 確認を出している間に、もう一度ウィンドウを閉じようとしたときは、重ねて出さない
        self.app.dialog_open = True
        self.assertEqual(confirm.ask(self.app, "タイマーをやめますか？", "", CHOICES), "continue")
        self.assertEqual(len(self.root.winfo_children()), 0)


if __name__ == "__main__":
    unittest.main()
