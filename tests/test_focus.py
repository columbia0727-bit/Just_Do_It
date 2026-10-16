from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import focus  # noqa: E402

START = datetime(2026, 10, 16, 9, 0, 0)


class RemainingSecondsTest(unittest.TestCase):
    def test_counts_down_from_start(self):
        self.assertEqual(focus.remaining_seconds(300, START, START), 300)
        self.assertEqual(focus.remaining_seconds(300, START, START + timedelta(seconds=61)), 239)

    def test_never_below_zero_after_sleep(self):
        # PC がスリープしている間に時間が過ぎても、マイナスにはならない
        self.assertEqual(focus.remaining_seconds(300, START, START + timedelta(hours=2)), 0)


class ElapsedMinutesTest(unittest.TestCase):
    def test_rounds_up(self):
        self.assertEqual(focus.elapsed_minutes(START, START + timedelta(minutes=3, seconds=1)), 4)
        self.assertEqual(focus.elapsed_minutes(START, START + timedelta(minutes=3)), 3)

    def test_at_least_one_minute(self):
        self.assertEqual(focus.elapsed_minutes(START, START), 1)
        self.assertEqual(focus.elapsed_minutes(START, START + timedelta(seconds=10)), 1)


class CanKeepGoingTest(unittest.TestCase):
    def test_after_five_minutes(self):
        self.assertTrue(focus.can_keep_going(focus.FOCUS_SHORT_SECONDS, done_mins=0, focus_minutes=25))

    def test_not_after_long_timer(self):
        self.assertFalse(focus.can_keep_going(25 * 60, done_mins=0, focus_minutes=25))

    def test_not_twice(self):
        # 「このまま続ける」で続けたタイマーの後には出さない
        self.assertFalse(focus.can_keep_going(focus.FOCUS_SHORT_SECONDS, done_mins=5, focus_minutes=25))

    def test_not_when_focus_is_not_longer(self):
        self.assertFalse(focus.can_keep_going(focus.FOCUS_SHORT_SECONDS, done_mins=0, focus_minutes=5))


if __name__ == "__main__":
    unittest.main()
