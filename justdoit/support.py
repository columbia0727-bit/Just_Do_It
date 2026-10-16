"""不具合の報告に使う情報と、報告の送り先（設定画面の「不具合を報告する」）

不具合の報告を受けたとき、利用者に「バージョンは？」「OS は？」と何度も聞き返さずに済むよう、
原因を絞り込むのに必要な情報を1回でまとめて送ってもらう。
作業内容・メールアドレス・トークンは含めない（他人に見せたくない内容や、登録の乗っ取りに使える情報のため）。
"""

from datetime import datetime
from pathlib import Path
import re
import sys

from justdoit import __version__, config, records, report_service

RECENT_ERRORS = 3  # error.log から含める、新しいエラーの件数

# 報告の送り先。GitHub の「不具合の報告」フォームと、GitHub のアカウントが無い人のためのメールアドレス
# （週次レポートの配信サービスと同じ、このアプリ専用のアカウント）
BUG_REPORT_URL = "https://github.com/columbia0727-bit/Just_Do_It/issues/new?template=bug_report.yml"
CONTACT_EMAIL = "justdoit.report@gmail.com"


def support_info(last_sync: datetime | None, now: datetime | None = None) -> str:
    """不具合の報告に使う情報（last_sync は、この起動で最後に同期できた時刻）"""
    now = now or datetime.now()
    edition = "配布版" if getattr(sys, "frozen", False) else "ソースから起動"
    lines = [
        f"Just do it. 不具合の報告用の情報（{now:%Y-%m-%d %H:%M}）",
        f"バージョン: {__version__}（{edition}）",
        f"OS: {config.os_description()}",
        f"保存先: {config.get_data_dir()}",
        f"作業ログ: {records_summary(config.get_csv_path())}",
        f"週次レポート: {report_summary(last_sync)}",
        "",
        "error.log（新しいもの）:",
        recent_errors(config.get_error_log_path()) or "なし",
    ]
    return "\n".join(lines)


def records_summary(csv_path: Path) -> str:
    """「123件（最新 2026-10-16 13:41）」（作業内容は含めない）"""
    try:
        saved = records.list_records(csv_path)
    except (OSError, UnicodeDecodeError) as e:
        return f"読み込めません（{type(e).__name__}: {e}）"
    if not saved:
        return "0件"
    return f"{len(saved)}件（最新 {saved[0].recorded_at:%Y-%m-%d %H:%M}）"


def report_summary(last_sync: datetime | None) -> str:
    """「登録済み・送信待ち 0件・最後に同期 10/16 13:40」（メールアドレスは含めない）"""
    if not report_service.is_registered():
        return "未登録"
    pending = len(report_service.load_queue(config.get_report_queue_path()))
    synced = f"{last_sync:%m/%d %H:%M}" if last_sync else "この起動ではまだ同期していません"
    return f"登録済み・送信待ち {pending}件・最後に同期 {synced}"


def recent_errors(error_log_path: Path, count: int = RECENT_ERRORS) -> str:
    """error.log の新しいほうから count 件（1件は「--- 日時（バージョン・OS）」で始まる）"""
    try:
        text = error_log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except OSError as e:
        return f"読み込めません（{e}）"
    # 各エラーは行の先頭の「--- 」から始まる（エラーの中身に「--- 」があっても、行の途中なら区切らない）
    entries = ["--- " + entry.strip() for entry in re.split(r"^--- ", text, flags=re.MULTILINE) if entry.strip()]
    return "\n\n".join(entries[-count:])
