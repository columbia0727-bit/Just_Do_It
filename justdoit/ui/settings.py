"""設定画面の土台と「全般」タブ（表示・タイマー・知らせ方）

「週次レポート」タブは report_settings.py にある。
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING
import webbrowser

from justdoit import __version__, config
from justdoit.ui import theme
from justdoit.ui.report_settings import TEXT_WIDTH, build_report_section
from justdoit.ui.theme import (
    C,
    make_checkbox,
    make_label,
    make_link,
    make_select,
    make_tabs,
)

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

SETTINGS_SIZE = (460, 560)
TABS = [("timer", "全般"), ("report", "週次レポート")]


def show_settings(app: JustDoItApp, tab: str | None = None) -> None:
    if tab:
        app.settings_tab = tab
    screen = app.make_screen(SETTINGS_SIZE)
    header = app.make_header(screen, "設定")
    def switch_tab(key: str) -> None:
        # 通信中はタブも切り替えない（戻るボタンと同じ理由）
        if not app.busy:
            show_settings(app, key)

    make_tabs(header, TABS, app.settings_tab, switch_tab).pack(side="left", padx=(app.px(16), 0))

    folder = build_data_folder(app, screen)
    version = build_version(app, screen)
    if app.settings_tab == "timer":
        build_timer_section(app, screen)
    else:
        build_report_section(app, screen)
    # 下の欄は、ほかの欄に押し出されないよう先に作っている。Tab キーでは見た目どおり最後に選ばれるよう、
    # 重なり順を上げる（Tab で選ぶ順は、この重なり順）
    version.lift()
    folder.lift()


def build_version(app: JustDoItApp, screen: tk.Frame) -> tk.Frame:
    """保存先の上: 今のバージョンと、新しいバージョンがあればダウンロードページへの案内"""
    row = tk.Frame(screen, bg=screen["bg"])
    row.pack(side="bottom", fill="x", pady=(0, app.px(6)))
    make_label(row, f"バージョン {__version__}", size=9, color=C.muted).pack(side="left")
    if app.new_release:
        release = app.new_release
        make_link(
            row, f"新しいバージョン {release.version} をダウンロード", lambda: webbrowser.open(release.url), accent=True
        ).pack(side="right")
    return row


def build_data_folder(app: JustDoItApp, screen: tk.Frame) -> tk.Frame:
    """画面の一番下: 作業ログの保存先と「フォルダを開く」"""
    footer = tk.Frame(screen, bg=screen["bg"])
    footer.pack(side="bottom", fill="x")
    make_label(
        footer,
        f"保存先: {config.get_data_dir()}",
        size=9,
        color=C.muted,
        wraplength=app.px(TEXT_WIDTH - 90),
        justify="left",
    ).pack(side="left", anchor="w")
    make_link(footer, "フォルダを開く", lambda: open_folder(app, config.get_data_dir())).pack(side="right")
    return footer


def open_folder(app: JustDoItApp, path: Path) -> None:
    """エクスプローラー（Mac は Finder）でフォルダを開く"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        # sys.platform で分ける（mypy が OS ごとに見分け、Windows にしかない os.startfile をエラーにしないように）
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as e:
        messagebox.showerror("エラー", f"フォルダを開けませんでした:\n{e}", parent=app.root)


# ==========================================
# 全般タブ（変えるとすぐ保存する）
# ==========================================
def build_timer_section(app: JustDoItApp, screen: tk.Frame) -> None:
    prefs = config.load_preferences()

    def change(**values):
        nonlocal prefs
        prefs = replace(prefs, **values)
        try:
            config.save_preferences(prefs)
        except OSError as e:
            messagebox.showerror("保存エラー", f"設定を保存できませんでした:\n{e}", parent=app.root)

    def change_appearance(index: int):
        change(appearance=theme.APPEARANCE_CHOICES[index][0])
        show_settings(app)  # 新しい色で作り直す

    def choose_minutes(key: str, choices: tuple[int, ...], index: int) -> None:
        change(**{key: choices[index]})

    def toggle(key: str, checked: bool) -> None:
        change(**{key: checked})

    rows = tk.Frame(screen, bg=screen["bg"])
    rows.pack(anchor="w")
    make_label(rows, "表示", bold=True).grid(row=0, column=0, columnspan=2, sticky="w")
    make_label(rows, "画面の色", size=11).grid(row=1, column=0, sticky="w", pady=3)
    make_select(
        rows,
        [label for _, label in theme.APPEARANCE_CHOICES],
        [key for key, _ in theme.APPEARANCE_CHOICES].index(prefs.appearance),
        change_appearance,
    ).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=3)

    make_label(rows, "タイマー", bold=True).grid(row=2, column=0, columnspan=2, sticky="w", pady=(16, 0))
    for row, (label, choices, current, key) in enumerate(
        [
            ("集中する長さ", config.FOCUS_MINUTE_CHOICES, prefs.focus_minutes, "focus_minutes"),
            ("休憩の長さ", config.BREAK_MINUTE_CHOICES, prefs.break_minutes, "break_minutes"),
        ],
        start=3,
    ):
        make_label(rows, label, size=11).grid(row=row, column=0, sticky="w", pady=3)
        make_select(
            rows,
            [f"{mins}分" for mins in choices],
            choices.index(current),
            partial(choose_minutes, key, choices),
        ).grid(row=row, column=1, sticky="w", padx=(12, 0), pady=3)
    make_label(screen, "「5分だけやる」はいつでも5分です。", size=10, color=C.muted).pack(anchor="w", pady=(2, 0))

    make_label(screen, "終わったときの知らせ方", bold=True).pack(anchor="w", pady=(18, 4))
    for text, key in [
        ("音を鳴らす", "notify_sound"),
        ("ウィンドウを前面に出す", "notify_front"),
        ("OS の通知を出す（画面の隅にお知らせが表示されます）", "notify_os"),
    ]:
        make_checkbox(screen, text, getattr(prefs, key), partial(toggle, key)).pack(anchor="w")

    def try_notify():
        app.notify("Just do it.", "通知のテストです。タイマーが終わるとこのように知らせます。", prefs)
        # 前面に出したままにならないよう、少ししたら元に戻す（画面を移っても必ず戻す）
        app.root.after(1500, lambda: app.bring_to_front(False))

    make_link(screen, "試しに知らせてみる", try_notify).pack(anchor="w", pady=(6, 0))
