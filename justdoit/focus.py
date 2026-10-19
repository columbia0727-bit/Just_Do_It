"""集中タイマーの判断（残り時間・記録する分数・「このまま続ける」を出すか）と、記録する前のタイマーの保存

画面（justdoit/ui/timer.py）から切り離し、時刻を渡して単体テストで確かめられるようにしている。
"""

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FOCUS_SHORT_SECONDS = 5 * 60  # 「5分だけやる」
# タイマーの途中で、最後に動いていた時刻を保存する間隔（落ちたときに失う時間は、最大でこの長さ）
HEARTBEAT_SECONDS = 30


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


# ==========================================
# 記録する前のタイマー
# ==========================================
@dataclass
class UnsavedTimer:
    """記録する前のタイマー

    タイマーの途中や記録画面で、アプリの強制終了・PC の電源切れなどが起きても作業時間を失わないよう、
    記録するまでファイルに残しておき、次に起動したときに記録できるようにする。
    """

    started_at: datetime  # 今のタイマーを始めた時刻
    last_seen: datetime  # 最後にアプリが動いていた時刻（タイマーの途中は HEARTBEAT_SECONDS ごとに更新する）
    duration_seconds: int  # タイマーの長さ
    done_mins: int = 0  # 「このまま続ける」の前までの分

    def minutes(self) -> int:
        """記録する分数（タイマーの長さを超えない）"""
        elapsed = elapsed_minutes(self.started_at, self.last_seen)
        return self.done_mins + min(elapsed, self.duration_seconds // 60)

    def worth_asking(self) -> bool:
        """次に起動したときに「記録しますか」と聞くか（始めてすぐ落ちた・1分も動いていないものは聞かない）"""
        return bool(self.done_mins) or (self.last_seen - self.started_at).total_seconds() >= 60


def save_unsaved(path: Path, timer: UnsavedTimer) -> None:
    """記録する前のタイマーを保存する（保存できなくても、タイマーは止めない）"""
    data = {
        "started_at": timer.started_at.isoformat(timespec="seconds"),
        "last_seen": timer.last_seen.isoformat(timespec="seconds"),
        "duration_seconds": timer.duration_seconds,
        "done_mins": timer.done_mins,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as e:
        logger.warning("記録する前のタイマーを保存できませんでした: %s", e)


def load_unsaved(path: Path) -> UnsavedTimer | None:
    """保存してある、記録する前のタイマー（無い・読めなければ None）"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UnsavedTimer(
            started_at=datetime.fromisoformat(data["started_at"]),
            last_seen=datetime.fromisoformat(data["last_seen"]),
            duration_seconds=int(data["duration_seconds"]),
            done_mins=int(data.get("done_mins", 0)),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning("記録する前のタイマーを読み込めませんでした: %s", e)
        return None


def clear_unsaved(path: Path) -> None:
    """記録した・記録しないと決めたタイマーを消す"""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("記録する前のタイマーを消せませんでした: %s", e)
