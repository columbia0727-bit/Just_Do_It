"""保存先のパスと設定ファイル（config.json）の読み書き"""

from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import platform
import sys

APP_NAME = "Just do it."
APP_DIR_NAME = "JustDoIt"

# リポジトリのルート（main.py があるフォルダ）
PROJECT_DIR = Path(__file__).resolve().parent.parent


def get_icon_path() -> Path:
    """アプリアイコンの画像（PyInstaller でビルドした場合は同梱したファイル）"""
    base = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
    return base / "assets" / "icon.png"


def get_data_dir() -> Path:
    """作業ログと設定ファイルの保存先ディレクトリを返す

    ソースから実行した場合は main.py と同じフォルダ、
    PyInstaller でビルドしたアプリの場合は OS 標準のユーザーデータフォルダを使う
    （.exe / .app の中には書き込めないため）。
    """
    if not getattr(sys, "frozen", False):
        return PROJECT_DIR

    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


def get_csv_path() -> Path:
    return get_data_dir() / "log" / "work_log.csv"


def get_report_queue_path() -> Path:
    return get_data_dir() / "log" / "report_queue.json"


def get_config_path() -> Path:
    return get_data_dir() / "config.json"


def load_config() -> dict:
    """config.json を読み込む（存在しない・壊れている場合は空の設定）"""
    try:
        with open(get_config_path(), encoding="utf-8") as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ==========================================
# 表示・タイマー・通知の設定（設定画面の「全般」タブ）
# ==========================================
FOCUS_MINUTE_CHOICES = (15, 20, 25, 30, 45, 50, 60, 90)
BREAK_MINUTE_CHOICES = (5, 10, 15, 20, 30)
APPEARANCES = ("system", "light", "dark")  # デバイスに合わせる / ライト / ダーク


@dataclass
class Preferences:
    focus_minutes: int = 25  # 「○分やる」の長さ（「5分だけやる」は固定）
    break_minutes: int = 10
    notify_sound: bool = True  # 音を鳴らす
    notify_front: bool = True  # ウィンドウを前面に出す
    notify_os: bool = True  # OS の通知を出す
    appearance: str = "system"  # 画面の色


def load_preferences() -> Preferences:
    """config.json の preferences を読み込む（無い・選択肢にない値は初期値にする）"""
    saved = load_config().get("preferences")
    saved = saved if isinstance(saved, dict) else {}
    prefs = Preferences()
    for field in fields(Preferences):
        value = saved.get(field.name)
        if isinstance(value, type(getattr(prefs, field.name))):
            setattr(prefs, field.name, value)
    if prefs.focus_minutes not in FOCUS_MINUTE_CHOICES:
        prefs.focus_minutes = Preferences.focus_minutes
    if prefs.break_minutes not in BREAK_MINUTE_CHOICES:
        prefs.break_minutes = Preferences.break_minutes
    if prefs.appearance not in APPEARANCES:
        prefs.appearance = Preferences.appearance
    return prefs


def save_preferences(prefs: Preferences) -> None:
    config = load_config()
    config["preferences"] = asdict(prefs)
    save_config(config)


# ==========================================
# エラーの記録（不具合を調べるときに使う）
# ==========================================
def get_error_log_path() -> Path:
    return get_data_dir() / "log" / "error.log"


def append_error_log(details: str) -> Path:
    """エラーの内容を日時とバージョンつきで log/error.log に追記し、そのファイルの場所を返す（書けなくても止めない）"""
    from datetime import datetime

    from justdoit import __version__

    path = get_error_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}（バージョン {__version__}）\n{details.rstrip()}\n\n")
    except OSError:
        pass
    return path
