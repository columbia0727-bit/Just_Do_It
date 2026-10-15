"""ビルドしたアプリの動作確認（JustDoIt --self-test）

HTTPS の通信に使うルート証明書を読み込めるかと、
サンプルの記録を一時フォルダに作ってすべての画面を一度ずつ表示し、エラーが起きないかを確かめる。
画面を持つアプリは、ビルドの設定（同梱するファイル）しだいで、ソースから起動したときは動くのに
配布版だけ動かないことがあるため、GitHub Actions でビルドした直後に Windows・macOS それぞれで実行する。
結果は selftest.log に書き、問題がなければ終了コード 0、あれば 1 で終わる。
"""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import tkinter as tk
import traceback

LOG_FILE = "selftest.log"


def run(log_path: Path = Path(LOG_FILE)) -> int:
    lines: list[str] = []
    try:
        failed = _check_certificates(lines)
        failed = _check_token_vault(lines) or failed
        failed = _run_screens(lines) or failed
    except Exception:
        lines.append("FAILED:\n" + traceback.format_exc())
        failed = True
    lines.append("RESULT: " + ("FAILED" if failed else "OK"))
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return 1 if failed else 0


def _check_certificates(lines: list[str]) -> bool:
    """HTTPS の通信に使うルート証明書を読み込めるか（読めないと、週次レポートの登録や更新の確認ができない）

    ネットワークにはつながず、証明書の一覧が読めたかだけを確かめる。
    """
    from justdoit import net

    count = net.root_certificate_count()
    lines.append(f"ルート証明書: {count} 件")
    if count == 0:
        lines.append("ルート証明書を読み込めませんでした（HTTPS の通信ができません）")
        return True
    return False


def _check_token_vault(lines: list[str]) -> bool:
    """Windows で、週次レポートのトークンを資格情報マネージャーに保存できるか

    keyring が配布版に同梱されていないと、気づかないまま config.json に保存されてしまうため、
    試しに保存・読み出し・削除してみる（実際のアプリのトークンとは別の名前を使う）。
    """
    import sys

    from justdoit import config

    if sys.platform != "win32":
        lines.append("トークンの保存先: config.json（本人だけが読める権限）")
        return False
    vault = config._vault()
    if vault is None:
        lines.append("トークンの保存先: 資格情報マネージャーを使えません（keyring が同梱されていない）")
        return True
    name = "--self-test--"
    try:
        vault.set_password(config.VAULT_SERVICE, name, "test")
        ok = vault.get_password(config.VAULT_SERVICE, name) == "test"
    finally:
        vault.delete_password(config.VAULT_SERVICE, name)
    lines.append("トークンの保存先: 資格情報マネージャー" + ("" if ok else "（読み出せません）"))
    return not ok


def _run_screens(lines: list[str]) -> bool:
    from justdoit import config, records, report_service, updates

    try:
        root = tk.Tk()
    except tk.TclError as e:
        # 画面（ディスプレイ）のない環境では確かめられないので、失敗にはしない
        lines.append(f"SKIPPED: 画面を開けませんでした ({e})")
        return False

    # 実際の記録・設定や、ネットワークには触れない
    tmp = Path(tempfile.mkdtemp())
    config.get_data_dir = lambda: tmp
    updates.check_for_update = lambda: None
    report_service.start_sync = lambda: None
    now = datetime.now()
    for days, task, minutes in [(40, "古い記録", 30), (6, "制作", 50), (2, "学習", 25), (0, "読書", 20)]:
        when = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        records.append_record_to_csv(config.get_csv_path(), when, task, minutes)

    from justdoit.ui import app as app_module
    from justdoit.ui import dashboard, history, settings, timer

    errors: list[str] = []
    root.report_callback_exception = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))
    app = app_module.JustDoItApp(root)

    def open_calendar() -> None:
        from justdoit.ui.datepicker import DatePicker

        timer.show_manual_record(app)
        root.update()
        pickers = [w for w in _find_widgets(root, "Label") if isinstance(w, DatePicker)]
        if not pickers:
            raise RuntimeError("手動記録に日付の欄がありません")
        pickers[0].open()

    screens = [
        ("メニュー", app.show_main_menu),
        ("初回の案内", app.show_welcome),
        ("集中タイマー", lambda: timer.show_focus_timer(app, 25 * 60)),
        ("記録画面", lambda: timer.show_record_form(app, 25, after_save=app.show_main_menu)),
        ("休憩タイマー", lambda: timer.show_break_timer(app)),
        ("手動記録", lambda: timer.show_manual_record(app)),
        ("手動記録（カレンダー）", open_calendar),
        ("振り返り（週）", lambda: dashboard.show_dashboard(app, "week")),
        ("振り返り（月）", lambda: dashboard.show_dashboard(app, "month")),
        ("振り返り（年）", lambda: dashboard.show_dashboard(app, "year")),
        ("記録一覧", lambda: history.show_history(app, back=app.show_main_menu)),
        ("設定（全般）", lambda: settings.show_settings(app, "timer")),
        ("設定（週次レポート）", lambda: settings.show_settings(app, "report")),
    ]
    for appearance in ("light", "dark"):
        # 週の目標も決めておき、メニューの「今週 … / 目標 …」も表示する
        config.save_preferences(config.Preferences(appearance=appearance, weekly_goal_minutes=180))
        for name, show in screens:
            before = len(errors)
            try:
                show()
                root.update()
            except Exception:
                errors.append(traceback.format_exc())
            ok = len(errors) == before
            lines.append(f"[{appearance}] {name}: {'OK' if ok else 'ERROR'}")

    # グラフは matplotlib のフォントなどが同梱されていないと描けないので、描けたかも確かめる
    dashboard.show_dashboard(app, "week")
    root.update()
    if not _find_widgets(root, "Canvas"):
        errors.append("振り返りのグラフが表示されていません")

    app.close_guard = None
    root.destroy()
    lines.extend(errors)
    return bool(errors)


def _find_widgets(widget: tk.Misc, widget_class: str) -> list[tk.Misc]:
    found = [widget] if widget.winfo_class() == widget_class else []
    for child in widget.winfo_children():
        found.extend(_find_widgets(child, widget_class))
    return found
