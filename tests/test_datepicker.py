from datetime import date
from pathlib import Path
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit.ui import theme  # noqa: E402
from justdoit.ui.datepicker import DatePicker  # noqa: E402

TODAY = date(2026, 10, 15)
FIRST = date(2026, 9, 14)


class DatePickerTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面（ディスプレイ）がない環境では確かめられない")
        self.addCleanup(self.root.destroy)
        self.addCleanup(setattr, theme, "_current_mode", None)
        theme.apply_theme(self.root, "light")
        self.root.geometry("400x400")
        self.chosen: list[date] = []
        self.screen_keys: list[str] = []
        for key in ("<Return>", "<Escape>", "<Left>"):
            self.root.bind(key, lambda event, key=key: self.screen_keys.append(key))
        self.picker = DatePicker(self.root, TODAY, first=FIRST, last=TODAY, on_select=self.chosen.append)
        self.picker.pack()
        self.root.update()

    def open(self):
        # キー入力はフォーカスのある部品に届くので、Tab キーで選んだ状態にしてから Enter を押す
        self.picker.focus_force()
        self.root.update()
        self.picker.event_generate("<Return>")
        self.root.update()
        self.assertIsNotNone(self.picker.popup)
        return self.picker.popup

    def day_cells(self, popup):
        return {
            int(cell.cget("text")): cell
            for frame in popup.winfo_children()
            for cell in frame.winfo_children()
            if isinstance(cell, tk.Label) and str(cell.cget("text")).isdigit()
        }

    def test_shows_today_and_chooses_with_keyboard(self):
        self.assertIn("今日 10/15（木）", self.picker.text)
        popup = self.open()
        popup.event_generate("<Left>")
        popup.event_generate("<Left>")
        popup.event_generate("<Return>")
        self.root.update()
        self.assertEqual(self.chosen, [date(2026, 10, 13)])
        self.assertIn("10/13（火）", self.picker.text)
        self.assertFalse(popup.winfo_exists(), "選んだらカレンダーを閉じる")
        # カレンダーの操作で、画面全体のキー（前の期間へ・保存など）が動かない
        self.assertEqual(self.screen_keys, [])

    def test_cannot_go_outside_the_range(self):
        popup = self.open()
        popup.event_generate("<Right>")  # 明日は選べない
        popup.event_generate("<Return>")
        self.assertEqual(self.chosen, [TODAY])

        popup = self.open()
        cells = self.day_cells(popup)
        cells[16].event_generate("<Button-1>")  # 明日を押しても選ばれない
        self.root.update()
        self.assertTrue(popup.winfo_exists())
        cells[1].event_generate("<Button-1>")  # 10/1 は範囲内
        self.root.update()
        self.assertEqual(self.chosen, [TODAY, date(2026, 10, 1)])

    def test_previous_month_up_to_the_first_day(self):
        popup = self.open()
        popup.change_month(-1)
        self.root.update()
        cells = self.day_cells(popup)
        self.assertEqual(len(cells), 30)  # 9月
        cells[13].event_generate("<Button-1>")  # 9/13 は選べる範囲（9/14〜）より前なので選べない
        cells[14].event_generate("<Button-1>")
        self.root.update()
        self.assertEqual(self.chosen, [FIRST])

    def test_escape_closes_without_choosing(self):
        popup = self.open()
        popup.event_generate("<Left>")
        popup.event_generate("<Escape>")
        self.root.update()
        self.assertFalse(popup.winfo_exists())
        self.assertEqual(self.chosen, [])
        self.assertEqual(self.picker.get(), TODAY)
        self.assertEqual(self.screen_keys, [], "Esc で前の画面に戻ってしまう")


if __name__ == "__main__":
    unittest.main()
