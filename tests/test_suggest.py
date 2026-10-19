from pathlib import Path
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit.ui.suggest import TaskSuggestions  # noqa: E402

COUNTS = [("英語の勉強", 166), ("英語", 36), ("読書", 68)]


class TaskSuggestionsTest(unittest.TestCase):
    """入力欄の候補が、打っているときだけ出て、押すと入力欄に入ること"""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        self.addCleanup(self.root.destroy)
        self.entry = tk.Entry(self.root)
        self.entry.pack()
        self.other = tk.Entry(self.root)
        self.other.pack()
        TaskSuggestions(self.entry, COUNTS)
        self.root.update()

    def shown(self) -> list[str]:
        """出ている候補の名前"""
        names = []
        for box in self.root.place_slaves():
            for row in box.winfo_children():
                names.append(row.winfo_children()[0].cget("text"))
        return names

    def type_text(self, text: str) -> None:
        self.entry.focus_force()
        self.root.update()
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.root.update()

    def test_shows_matching_names_while_typing(self):
        self.type_text("英")
        self.assertEqual(self.shown(), ["英語の勉強", "英語"])
        self.type_text("")
        self.assertEqual(self.shown(), [])

    def test_choosing_fills_the_entry_and_hides(self):
        self.type_text("英")
        row = self.root.place_slaves()[0].winfo_children()[1]
        row.winfo_children()[0].event_generate("<Button-1>")
        self.root.update()
        # 「英語」を選んでも、それを含む「英語の勉強」が続けて出ない
        self.assertEqual((self.entry.get(), self.shown()), ("英語", []))

    def test_not_shown_when_filled_without_typing(self):
        # 記録一覧で記録を選んで、入力欄に名前が入ったときなどは出さない
        self.other.focus_force()
        self.root.update()
        self.entry.insert(0, "英")
        self.root.update()
        self.assertEqual(self.shown(), [])

    def test_escape_hides_only_the_suggestions(self):
        went_back = []
        self.root.bind("<Escape>", lambda event: went_back.append(True))
        self.type_text("英")
        self.entry.event_generate("<Escape>")
        self.root.update()
        self.assertEqual((self.shown(), went_back), ([], []))


if __name__ == "__main__":
    unittest.main()
