"""タイマー終了の知らせ方（音・OS の通知）。追加のライブラリを使わず、OS 標準の仕組みを呼び出す

どれも失敗してもアプリは止めない（通知が出ないだけ）。
"""

import platform
import subprocess
from xml.sax.saxutils import escape

# Windows の通知は、登録済みのアプリの名前（AppUserModelID）で出す必要がある。
# 配布用のインストーラーを作っていないため、Windows に最初から入っている PowerShell の名前を借りる
WINDOWS_NOTIFIER_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
MAC_SOUND = "/System/Library/Sounds/Glass.aiff"


def play_sound() -> bool:
    """OS の通知音を鳴らす。鳴らせなかったら False（呼び出し側で Tk の bell() を使う）"""
    try:
        system = platform.system()
        if system == "Windows":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return True
        if system == "Darwin":
            subprocess.Popen(["afplay", MAC_SOUND])
            return True
    except (OSError, RuntimeError):
        pass
    return False


def show_notification(title: str, message: str) -> None:
    """OS の通知（Windows のトースト通知・macOS の通知センター）を出す"""
    try:
        system = platform.system()
        if system == "Windows":
            _show_windows_toast(title, message)
        elif system == "Darwin":
            script = f"display notification {_applescript_string(message)} with title {_applescript_string(title)}"
            subprocess.Popen(["osascript", "-e", script])
        else:
            subprocess.Popen(["notify-send", title, message])
    except OSError as e:
        print(f"⚠️ 通知を出せませんでした: {e}")


def _show_windows_toast(title: str, message: str) -> None:
    toast_xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(title)}</text><text>{escape(message)}</text>"
        "</binding></visual></toast>"
    )
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] > $null;"
        "$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument,"
        " ContentType = WindowsRuntime]::new();"
        f"$xml.LoadXml({_powershell_string(toast_xml)});"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        f"CreateToastNotifier({_powershell_string(WINDOWS_NOTIFIER_ID)}).Show($toast)"
    )
    # 黒い画面が一瞬出ないよう、ウィンドウを作らずに実行する
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _powershell_string(text: str) -> str:
    """PowerShell の '...' 文字列にする（' は '' と書く）"""
    return "'" + text.replace("'", "''") + "'"


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
