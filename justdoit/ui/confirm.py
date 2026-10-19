"""確認（「タイマーをやめますか？」など）を、アプリの画面の上に重ねて出す

OS 標準の確認ダイアログは、Mac ではボタンが「Yes / No」と英語になり、設定では日本語にできなかった。
自作して、ボタンを「やめてメニューに戻る」「タイマーを続ける」のように、押すと何が起きるかがわかる言葉にする。
取り返しがつく方（続ける・やめておく）を塗りつぶしのボタンにし、Enter・Esc でもそちらを選ぶ（押し間違えても失わない）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
import tkinter as tk
from typing import TYPE_CHECKING

from justdoit.ui.theme import C, make_button, make_label

if TYPE_CHECKING:
    from justdoit.ui.app import JustDoItApp

CARD_WIDTH = 300  # 確認のカードの幅（狭い画面では、画面の幅に合わせる）
CARD_PADDING = 20


@dataclass
class Choice[T]:
    """確認のボタン1つ分。safe は取り返しがつく方（塗りつぶしにし、Enter・Esc でも選ぶ）"""

    label: str
    value: T
    safe: bool = False


def ask[T](app: JustDoItApp, title: str, message: str, choices: list[Choice[T]]) -> T:
    """確認を出し、押されたボタンの value を返す（押されるまで待つ）

    Esc を押したときや、確認を出している間に画面が切り替わったとき（タイマーが終わったなど）は、
    safe のボタンを選んだことにする。
    """
    safe = next(choice for choice in choices if choice.safe)
    if app.dialog_open:  # 確認を出している間に、もう一度ウィンドウを閉じようとしたときなど
        return safe.value
    chosen: list[Choice[T]] = []
    done = tk.BooleanVar(value=False)

    def choose(choice: Choice[T]) -> None:
        if not chosen:
            chosen.append(choice)
        done.set(True)

    cover = make_dialog(app, title, message, choices, choose)

    def on_destroy(event: tk.Event) -> None:
        if event.widget is cover:
            choose(safe)

    cover.bind("<Destroy>", on_destroy)
    app.dialog_open = True
    try:
        # 確認に答えるまで、後ろの画面は押せないようにする
        cover.grab_set()
        cover.focus_set()
        app.root.wait_variable(done)
    except tk.TclError:  # 確認を出している間にアプリが終了した
        pass
    finally:
        app.dialog_open = False
    if cover.winfo_exists():
        cover.destroy()
    return (chosen[0] if chosen else safe).value


def make_dialog[T](
    app: JustDoItApp, title: str, message: str, choices: list[Choice[T]], on_choose: Callable[[Choice[T]], object]
) -> tk.Frame:
    """確認を画面に重ねて出す（押されるのは待たない。動作確認でも使う）。重ねた部品（カバー）を返す

    後ろの画面は背景色で覆い、真ん中にカードを置く（Tk では後ろを半透明で暗くできず、
    覆わないと後ろの画面が中途半端に見えて、どこまでが確認かわかりにくかった）。
    """
    width = min(app.px(CARD_WIDTH), app.root.winfo_width() - app.px(32))
    text_width = width - app.px(CARD_PADDING) * 2
    cover = tk.Frame(app.root, bg=C.bg)
    cover.place(x=0, y=0, relwidth=1, relheight=1)
    # カードは画面と同じ背景色にし、枠線で区切る（枠線だけのボタンは背景色で塗るので、カードの色を変えると浮いて見える）
    card = tk.Frame(
        cover,
        bg=C.bg,
        padx=app.px(CARD_PADDING),
        pady=app.px(CARD_PADDING),
        highlightthickness=1,
        highlightbackground=C.border,
        highlightcolor=C.border,
    )
    make_label(card, title, size=13, bold=True, wraplength=text_width, justify="left").pack(anchor="w")
    make_label(card, message, size=11, color=C.muted, wraplength=text_width, justify="left").pack(
        anchor="w", pady=(app.px(6), app.px(16))
    )
    # ボタンは縦に並べる（「やめてメニューに戻る」のような長い言葉でも、幅が足りるように）
    for number, choice in enumerate(choices):
        button = make_button(card, choice.label, partial(on_choose, choice), primary=choice.safe)
        button.pack(fill="x", pady=(app.px(8) if number else 0, 0))

    safe = next(choice for choice in choices if choice.safe)

    def choose_safe(event: tk.Event) -> str:
        on_choose(safe)
        return "break"  # 画面全体に登録したキー（Esc で前の画面に戻るなど）が続けて動かないように

    cover.bind("<Escape>", choose_safe)
    cover.bind("<Return>", choose_safe)

    card.place(relx=0.5, rely=0.5, anchor="center", width=width)
    cover.lift()
    return cover
