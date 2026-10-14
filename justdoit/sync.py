"""同じメールアドレスで週次レポートに登録した PC 同士で、記録を同期する

同期の流れ
1. 送信待ちキュー（この PC で付けた・直した・消した記録）を、先に配信サービスへ送りきる
2. 配信サービスから、その利用者の記録と「消した記録の ID」を受け取る（通信は別スレッドで行う）
3. 手元の CSV と突き合わせる（画面のスレッドで行う。記録の保存と同時に CSV を書き換えないように）
   - ほかの PC で消された記録は、手元からも消す
   - 手元にない記録は、手元に加える
   - サーバーにない手元の記録（登録前の記録など）は、サーバーへ送る

記録の同一性は、記録の内容（日時・作業内容・時間）から作る ID（report_service.log_id）で判断する。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from justdoit import config, report_service
from justdoit.records import DATETIME_FORMAT, parse_minutes, read_rows, write_rows
from justdoit.report_service import ReportServiceError


@dataclass
class ServerState:
    """配信サービスから受け取った、その利用者の記録"""

    logs: list[dict]  # {"datetime", "task", "minutes", "id"}
    deleted: set[str]  # 消した記録の ID
    schedule: tuple[int, int]  # 届くタイミング（曜日, 時）
    retention_days: int  # サーバーが記録を預かる日数


@dataclass
class SyncResult:
    added: int = 0  # ほかの PC から取り込んだ記録の数
    removed: int = 0  # ほかの PC で消された記録の数
    pushed: list[dict] = field(default_factory=list)  # サーバーへ送る、手元にしかない記録

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def fetch_server_state() -> ServerState:
    """送信待ちの記録を送りきってから、配信サービスの記録を受け取る（別スレッドから呼ぶ）

    送信待ちが残ったまま突き合わせると、まだ届いていない「消した」が無視されて、
    消した記録がサーバーから戻ってきてしまうため、送りきれなければ ReportServiceError を送出する。
    """
    url = report_service.get_service_url()
    queue_path = config.get_report_queue_path()
    report_service.sync_queue(url, queue_path, wait=True)
    if report_service.load_queue(queue_path):
        raise ReportServiceError("サーバーに接続できませんでした。時間をおいて再度お試しください", "network")

    token = config.load_config().get("report_token")
    result = report_service.call_service(url, {"action": "sync_pull", "token": token})
    return ServerState(
        logs=list(result.get("logs", [])),
        deleted=set(result.get("deleted", [])),
        schedule=(int(result.get("weekday", 0)), int(result.get("hour", 9))),
        retention_days=int(result.get("retention_days", 400)),
    )


def merge(csv_path: Path, state: ServerState, now: datetime | None = None) -> SyncResult:
    """手元の CSV と配信サービスの記録を突き合わせて、CSV を書き直す（画面のスレッドから呼ぶ）"""
    result = SyncResult()
    server_ids = {log["id"] for log in state.logs}
    # 消したあとに同じ内容の記録を付け直した場合は、サーバーにある記録を正とする
    deleted = state.deleted - server_ids
    # サーバーが預かっている期間より前の記録は、サーバーに無くて当然なので送らない
    window_start = (now or datetime.now()) - timedelta(days=state.retention_days)

    kept_rows: list[list[str]] = []
    local_ids: set[str] = set()
    for row in read_rows(csv_path):
        log = _row_to_log(row)
        if log is None:
            kept_rows.append(row)  # 読めない行は、そのまま残す
            continue
        log_id = report_service.log_id(log)
        if log_id in deleted:
            result.removed += 1
            continue
        kept_rows.append(row)
        local_ids.add(log_id)
        recorded_at = datetime.strptime(log["datetime"], DATETIME_FORMAT)
        if log_id not in server_ids and recorded_at >= window_start:
            result.pushed.append(log)

    new_logs = sorted(
        (log for log in state.logs if log["id"] not in local_ids and log["id"] not in deleted),
        key=lambda log: log["datetime"],
    )
    new_rows = [[log["datetime"], log["task"], f"{log['minutes']}分"] for log in new_logs]
    result.added = len(new_rows)

    if result.changed:
        write_rows(csv_path, kept_rows + new_rows)
    return result


def apply(state: ServerState) -> SyncResult:
    """受け取った記録を手元に反映し、手元にしかない記録をサーバーへ送る（画面のスレッドから呼ぶ）"""
    result = merge(config.get_csv_path(), state)
    if result.pushed:
        report_service.enqueue_logs(config.get_report_queue_path(), result.pushed)
        report_service.start_sync()

    # 届くタイミングは利用者ごとに1つ（あとから変えた PC の値）なので、ほかの PC で変えた値に表示を合わせる
    settings = config.load_config()
    if report_service.get_schedule(settings) != state.schedule:
        report_service.save_schedule(settings, *state.schedule)
        config.save_config(settings)
    return result


def _row_to_log(row: list[str]) -> dict | None:
    if len(row) < 3:
        return None
    try:
        datetime.strptime(row[0], DATETIME_FORMAT)
    except ValueError:
        return None
    minutes = parse_minutes(row[2])
    if minutes <= 0:
        return None
    return report_service.make_log(row[0], row[1].strip(), minutes)
