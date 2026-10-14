"""週次レポート配信サービス（gas/report_service/）との通信と、送信待ちキュー

記録は送信待ちキュー（log/report_queue.json）に積んでから別スレッドで送る。
通信できなかった分はキューに残り、次の記録時・次回起動時に再送される。
（登録前の記録や、ほかの PC との記録のやり取りは sync.py で行う）
"""

import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.request

from justdoit import config, net

# 開発者がデプロイした gas/report_service/ の WebアプリURL
# 環境変数 JUSTDOIT_REPORT_URL が設定されていればそちらを優先する
REPORT_SERVICE_URL = "https://script.google.com/macros/s/AKfycbwsGmQMb4egG6jISjSEh1KR3QIEDJ-AxTSdWUhMFVB9GWOn2f1WZEg6koFYFOS8_jutpQ/exec"
# GAS は起動やロック待ち（最大10秒）で遅れることがあるため、余裕を持たせる
# （短すぎると、サーバーでは保存済みなのに失敗扱いになって再送してしまう）
TIMEOUT_SECONDS = 30

# レポートが届くタイミング（曜日は 0=月 … 6=日。GAS 側の範囲と合わせる）
WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]
REPORT_HOURS = range(6, 24)
DEFAULT_SCHEDULE = (0, 9)  # 月曜 9時台


class ReportServiceError(Exception):
    """配信サービスのエラー。code は "network"（通信失敗）や "unauthorized"（トークン無効）など"""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def get_service_url() -> str:
    return os.environ.get("JUSTDOIT_REPORT_URL") or REPORT_SERVICE_URL


def is_registered() -> bool:
    return bool(get_service_url() and config.load_config().get("report_token"))


def get_schedule(settings: dict) -> tuple[int, int]:
    """設定に保存された「届くタイミング」(曜日, 時) を返す（未設定・不正な値なら既定のタイミング）"""
    weekday, hour = settings.get("report_weekday"), settings.get("report_hour")
    if weekday in range(len(WEEKDAY_NAMES)) and hour in REPORT_HOURS:
        return weekday, hour
    return DEFAULT_SCHEDULE


def save_schedule(settings: dict, weekday: int, hour: int) -> None:
    settings["report_weekday"] = weekday
    settings["report_hour"] = hour


def format_schedule(weekday: int, hour: int) -> str:
    """「毎週月曜 9時ごろ」の形にする（GAS のトリガーは分単位では動かないので「ごろ」）"""
    return f"毎週{WEEKDAY_NAMES[weekday]}曜 {hour}時ごろ"


# ==========================================
# 通信
# ==========================================
def post_json(url: str, payload: dict) -> dict:
    """JSON を POST し、レスポンスの JSON を dict で返す"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with net.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        return json.loads(res.read().decode("utf-8"))


def call_service(url: str, payload: dict) -> dict:
    """配信サービスを呼び出して結果の dict を返す。失敗時は ReportServiceError を送出"""
    try:
        result = post_json(url, payload)
    except (OSError, ValueError) as e:
        raise ReportServiceError(f"サーバーに接続できませんでした: {e}", "network") from e
    if result.get("status") != "success":
        raise ReportServiceError(result.get("message", "不明なエラー"), result.get("code", "error"))
    return result


# ==========================================
# 送信待ちキュー
# ==========================================
# キューは UI スレッド（追加）と送信スレッド（削除）の両方から触るためロックで守る
_queue_lock = threading.Lock()
# 送信スレッドが同時に複数動かないようにする
_sync_lock = threading.Lock()


# キューに積むものは3種類（action が無いものは、以前のバージョンで積んだ「記録の追加」）
#   記録の追加: {"datetime", "task", "minutes"}
#   記録の修正: {"action": "update_log", "datetime", "task", "minutes", "new_task", "new_minutes"}
#   記録の削除: {"action": "delete_log", "datetime", "task", "minutes"}
# 修正・削除も追加と同じキューに積むことで、オフライン中に直した場合も順番どおりに反映される
def make_log(datetime_str: str, task: str, minutes: int) -> dict:
    return {"datetime": datetime_str, "task": task, "minutes": minutes}


def make_update(log: dict, new_task: str, new_minutes: int) -> dict:
    return {"action": "update_log", **log, "new_task": new_task, "new_minutes": new_minutes}


def make_delete(log: dict) -> dict:
    return {"action": "delete_log", **log}


def log_id(log: dict) -> str:
    """記録の内容から決まるID。再送や再登録で同じ記録を送ってもサーバー側で重複を防げ、
    記録一覧で直した・消した記録をサーバー側で探す手がかりにもなる"""
    key = f"{log['datetime']}|{log['task']}|{log['minutes']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def build_payload(item: dict, token: str) -> dict:
    """キューの1件を、配信サービスへ送る形にする"""
    payload = {"action": "log", **item, "token": token, "id": log_id(item)}
    if payload["action"] == "update_log":
        payload["new_id"] = log_id(make_log(item["datetime"], item["new_task"], item["new_minutes"]))
    return payload


def load_queue(queue_path: Path) -> list[dict]:
    try:
        with open(queue_path, encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_queue(queue_path: Path, items: list[dict]) -> None:
    # 書き込み途中でアプリが終了してもファイルが壊れないよう、一時ファイルから置き換える
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = queue_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, queue_path)


def enqueue_logs(queue_path: Path, items: list[dict]) -> None:
    with _queue_lock:
        save_queue(queue_path, load_queue(queue_path) + list(items))


def clear_registration() -> None:
    """保存済みのトークンと送信待ちの記録を削除する"""
    settings = config.load_config()
    settings.pop("report_token", None)
    settings.pop("report_email", None)
    config.save_config(settings)
    with _queue_lock:
        save_queue(config.get_report_queue_path(), [])


def sync_queue(url: str, queue_path: Path, wait: bool = False) -> None:
    """送信待ちの記録（追加・修正・削除）を配信サービスへ順に送る（別スレッドから呼ぶ）

    トークンが無効になっていた場合（メールのリンクから配信停止された等）は登録を解除する。
    ほかのスレッドが送信中なら、wait=False ではそのまま戻り、wait=True ではそれが終わるのを待ってから送る。
    """
    if not _sync_lock.acquire(blocking=wait):
        return
    try:
        while True:
            token = config.load_config().get("report_token")
            with _queue_lock:
                pending = load_queue(queue_path)
            if not token or not pending:
                return

            processed = 0
            stop = False
            for item in pending:
                try:
                    call_service(url, build_payload(item, token))
                except ReportServiceError as e:
                    if e.code in ("network", "busy"):
                        print(f"⚠️ 週次レポート用の記録を送信できませんでした（次回再送）: {e}")
                        stop = True
                        break
                    if e.code == "unauthorized":
                        print("⚠️ 週次レポートの登録が解除されていました")
                        clear_registration()
                        return
                    # 形式エラーなど再送しても成功しない記録は捨てる
                    print(f"⚠️ 週次レポート用の記録を送信できませんでした（破棄）: {e}")
                processed += 1

            # 送信中に追加された記録はキューの末尾にあるので、先頭から送信済みの分だけ取り除く
            with _queue_lock:
                save_queue(queue_path, load_queue(queue_path)[processed:])
            if stop or processed == 0:
                return
    finally:
        _sync_lock.release()


def start_sync() -> None:
    """登録済みなら、送信待ちの記録を別スレッドで送り始める"""
    if is_registered():
        threading.Thread(
            target=sync_queue, args=(get_service_url(), config.get_report_queue_path()), daemon=True
        ).start()
