"""保存先のパスと設定ファイル（config.json）の読み書き"""

from dataclasses import asdict, dataclass, fields
import json
import logging
import os
from pathlib import Path
import platform
import sys
from typing import Protocol

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

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


def get_csv_path() -> Path:
    return get_data_dir() / "log" / "work_log.csv"


def get_report_queue_path() -> Path:
    return get_data_dir() / "log" / "report_queue.json"


def get_unsaved_timer_path() -> Path:
    """記録する前のタイマー（アプリや PC が落ちても、次に起動したときに記録できるように残す）"""
    return get_data_dir() / "log" / "unsaved_timer.json"


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
    if sys.platform != "win32":
        # macOS では週次レポートのトークンをここに保存するので、本人以外は読めないようにする
        os.chmod(path, 0o600)


# ==========================================
# 週次レポートの登録トークン（配信サービスで本人だと確かめるための合言葉）
#
# Windows は、OS の「資格情報マネージャー」に保存する（config.json を見られても漏れないように）。
# macOS は config.json に保存し、本人以外は読めない権限にする。キーチェーンに保存しないのは、
# 署名していないアプリは更新のたびにキーチェーンへのアクセスの許可（パスワード入力）を求められるため。
# ==========================================
TOKEN_KEY = "report_token"
VAULT_SERVICE = "Just do it. 週次レポート"


class Vault(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


def _vault() -> Vault | None:
    """トークンを保存する OS の仕組み（使えなければ None。config.json に保存する）"""
    if sys.platform != "win32":
        return None
    try:
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    except Exception:  # keyring が無い・使えない環境では config.json に保存する
        return None


def _vault_user() -> str:
    # 保存先フォルダごとに分ける（ソースから実行したとき・テストのときに、配布版のトークンと混ざらないように）
    return str(get_data_dir())


def get_report_token() -> str:
    """保存済みのトークン（未登録なら空）"""
    vault = _vault()
    if vault is not None:
        try:
            token = vault.get_password(VAULT_SERVICE, _vault_user())
            if token:
                return token
        except Exception:
            pass
    # 資格情報マネージャーを使えないとき・移す前のトークンは、config.json から読む
    token = load_config().get(TOKEN_KEY)
    return token if isinstance(token, str) else ""


def set_report_token(token: str) -> None:
    """トークンを保存する（資格情報マネージャーに保存できたら、config.json からは消す）"""
    config = load_config()
    vault = _vault()
    if vault is not None:
        try:
            vault.set_password(VAULT_SERVICE, _vault_user(), token)
            if TOKEN_KEY in config:
                del config[TOKEN_KEY]
                save_config(config)
            return
        except Exception:
            pass  # 保存できなければ config.json に保存する
    config[TOKEN_KEY] = token
    save_config(config)


def clear_report_token() -> None:
    vault = _vault()
    if vault is not None:
        try:
            vault.delete_password(VAULT_SERVICE, _vault_user())
        except Exception:
            pass  # 保存していなかった
    config = load_config()
    if TOKEN_KEY in config:
        del config[TOKEN_KEY]
        save_config(config)


def migrate_report_token() -> None:
    """以前のバージョンが config.json に保存したトークンを、資格情報マネージャーに移す（起動時に呼ぶ）"""
    token = load_config().get(TOKEN_KEY)
    if isinstance(token, str) and token and _vault() is not None:
        try:
            set_report_token(token)
        except OSError:
            pass  # 移せなくても、config.json から読めるので動く


# ==========================================
# 表示・タイマー・通知の設定（設定画面の「全般」タブ）
# ==========================================
FOCUS_MINUTE_CHOICES = (15, 20, 25, 30, 45, 50, 60, 90)
BREAK_MINUTE_CHOICES = (5, 10, 15, 20, 30)
APPEARANCES = ("system", "light", "dark")  # デバイスに合わせる / ライト / ダーク
# 週の目標（分）。0 は目標なし。週次レポートに登録していれば、配信サービスにも保存してほかの PC とそろえる
WEEKLY_GOAL_CHOICES = (0, 60, 120, 180, 300, 420, 600, 900, 1200)


@dataclass
class Preferences:
    focus_minutes: int = 25  # 「○分やる」の長さ（「5分だけやる」は固定）
    break_minutes: int = 10
    notify_sound: bool = True  # 音を鳴らす
    notify_front: bool = True  # ウィンドウを前面に出す
    notify_os: bool = True  # OS の通知を出す
    appearance: str = "system"  # 画面の色
    weekly_goal_minutes: int = 0  # 週の目標（0 は目標なし）


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
    if prefs.weekly_goal_minutes not in WEEKLY_GOAL_CHOICES:
        prefs.weekly_goal_minutes = Preferences.weekly_goal_minutes
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


def os_description() -> str:
    """OS の名前とバージョン（例: 「macOS 15.1」「Windows 11 (10.0.26100)」。問い合わせのときに原因を絞り込むため）"""
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.version()})"
    return f"{platform.system()} {platform.release()}"


def append_error_log(details: str) -> Path:
    """エラーの内容を日時・バージョン・OS つきで error.log に追記し、ファイルの場所を返す（書けなくても止めない）"""
    from datetime import datetime

    from justdoit import __version__

    path = get_error_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            header = f"--- {datetime.now():%Y-%m-%d %H:%M:%S}（バージョン {__version__}・{os_description()}）"
            f.write(f"{header}\n{details.rstrip()}\n\n")
    except OSError:
        pass
    return path


class ErrorLogHandler(logging.Handler):
    """ログの警告・エラーを error.log に残す（配布版は画面だけのアプリで、コンソールに出しても見えないため）"""

    def emit(self, record: logging.LogRecord) -> None:
        append_error_log(self.format(record))


def setup_logging() -> None:
    """ログの出し先を決める（起動したときに1回呼ぶ）

    警告・エラーは error.log に残す。ソースから起動したときは、記録の保存などの情報もコンソールに出す。
    """
    logger = logging.getLogger("justdoit")
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    to_file = ErrorLogHandler(logging.WARNING)
    to_file.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger.addHandler(to_file)
    # 配布版（画面だけのアプリ）では sys.stderr が無い
    if sys.stderr is not None:
        to_console = logging.StreamHandler()
        to_console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(to_console)
