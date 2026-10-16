"""集中タイマーの判断（残り時間・記録する分数・「このまま続ける」を出すか）

画面（justdoit/ui/timer.py）から切り離し、時刻を渡して単体テストで確かめられるようにしている。
"""

from datetime import datetime

FOCUS_SHORT_SECONDS = 5 * 60  # 「5分だけやる」


def remaining_seconds(total_seconds: int, start: datetime, now: datetime) -> int:
    """残り秒数（開始時刻との差から計算するので、PC がスリープしてもずれない。0 より小さくはしない）"""
    return max(0, total_seconds - int((now - start).total_seconds()))


def elapsed_minutes(start: datetime, now: datetime) -> int:
    """start から now までの分数（途中で終えたときに記録する時間）。1分未満でも最低「1分」として切り上げる"""
    elapsed_secs = int((now - start).total_seconds())
    return max(1, (elapsed_secs + 59) // 60)


def can_keep_going(duration_seconds: int, done_mins: int, focus_minutes: int) -> bool:
    """タイマーが終わったときに「このまま続ける」を出すか

    「5分だけやる」が終わったときだけ、乗ってきたら設定した集中の長さまで続けられるようにする（このアプリの考え方）。
    続けた後（done_mins がある）や、集中の長さが5分以下のときは出さない。
    """
    return not done_mins and duration_seconds == FOCUS_SHORT_SECONDS and focus_minutes > duration_seconds // 60
