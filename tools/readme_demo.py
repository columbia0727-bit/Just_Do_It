"""README の冒頭のデモ（docs/demo.gif）を、サンプルの記録でアプリを自動で操作して作る

「5分だけやる」→ 途中で終えて記録 → 振り返り、の流れを、ボタンを押しながら撮る（押すところは緑の丸で示す）。
画面を録画すると、後ろのウィンドウや本物の記録が写ってしまうため、README の画像と同じく一時フォルダの記録で作る。

    python tools/readme_demo.py                  # docs/demo.gif に保存する
    python tools/readme_demo.py 保存先.gif        # 確かめたいときは、別の場所に保存する

Mac では、ターミナル（または Python）に「画面収録」の許可が要る。作っている間は、ほかのウィンドウを重ねない。
"""

from collections.abc import Callable
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from PIL import Image, ImageDraw, ImageGrab  # noqa: E402

from justdoit import config, updates  # noqa: E402
from tools.readme_screenshots import WEEKLY_GOAL_MINUTES, find_widgets, write_sample_records  # noqa: E402

SCALE = 1.25  # 画面の大きさに対する倍率（README のスクリーンショットとそろえる）
CANVAS_SIZE = (970, 730)  # GIF の大きさ（いちばん大きい振り返りの画面が入る大きさ）
CANVAS_COLOR = "#e4e4e0"  # ウィンドウの外側の色
FRAME_MS = 250  # 撮る間隔
SETTLE_MS = 600  # 画面を切り替えてから撮り始めるまで待つ時間


def main(out_path: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    config.get_data_dir = lambda: tmp
    updates.check_for_update = lambda: None
    write_sample_records(config.get_csv_path(), datetime.now())
    config.save_preferences(config.Preferences(weekly_goal_minutes=WEEKLY_GOAL_MINUTES, appearance="light"))

    from justdoit.ui import app as app_module
    from justdoit.ui.theme import PillButton

    root = tk.Tk()
    app = app_module.JustDoItApp(root)
    # ほかのウィンドウに隠れていると、その上から撮ってしまうので、いちばん前に出しておく
    root.attributes("-topmost", True)
    if sys.platform == "darwin":
        script = 'tell application "System Events" to set frontmost of (first process whose unix id is {}) to true'
        subprocess.run(["osascript", "-e", script.format(os.getpid())], capture_output=True)
    root.focus_force()

    frames: list[tuple[Image.Image, int]] = []  # (画像, 表示する時間 ms)

    def grab(ring_on: tk.Misc | None = None) -> Image.Image:
        """ウィンドウを撮り、GIF の大きさの台紙の真ん中に置く（ring_on を渡すと、その部品に緑の丸を描く）"""
        root.update()
        x, y, width, height = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        size = (round(width * SCALE), round(height * SCALE))
        window = ImageGrab.grab(bbox=(x, y, x + width, y + height)).convert("RGB")
        window = window.resize(size, Image.Resampling.LANCZOS)
        if ring_on is not None:
            # 横に長いボタンは右寄りを押す（真ん中だと、丸と矢印がボタンの文字に重なって読めない）
            share = 0.8 if ring_on.winfo_width() > 150 else 0.5
            cx = round((ring_on.winfo_rootx() - x + ring_on.winfo_width() * share) * SCALE)
            cy = round((ring_on.winfo_rooty() - y + ring_on.winfo_height() / 2) * SCALE)
            window = draw_click(window, cx, cy)
        canvas = Image.new("RGB", CANVAS_SIZE, CANVAS_COLOR)
        left, top = (CANVAS_SIZE[0] - size[0]) // 2, (CANVAS_SIZE[1] - size[1]) // 2
        ImageDraw.Draw(canvas).rectangle((left - 1, top - 1, left + size[0], top + size[1]), outline="#cfcfca")
        canvas.paste(window, (left, top))
        return canvas

    def button(text: str) -> tk.Misc:
        return next(w for w in find_widgets(root, PillButton) if w.text == text)

    def link(text: str) -> tk.Misc:
        return next(w for w in find_widgets(root, tk.Label) if w.cget("text") == text)

    def show_menu() -> None:
        app.show_main_menu()

    # 手順：（何をするか, 撮る時間 ms）。押す部品を返す手順では、押す前に緑の丸を見せてから押す
    steps: list[tuple[Callable[[], tk.Misc | None], int]] = [
        (show_menu, 1500),
        (lambda: button("5分だけやる"), 0),
        (lambda: None, 3000),  # タイマーが進むところ
        (lambda: button("ここで終える"), 0),
        (lambda: None, 1000),
        (lambda: button("英語の勉強"), 0),
        (lambda: None, 1000),
        (lambda: button("記録する"), 0),
        (lambda: None, 1500),  # メニューの「今日」が増えたところ
        (lambda: link("振り返り"), 0),
        (lambda: None, 3000),
    ]

    def run(index: int) -> None:
        if index == len(steps):
            app.close_guard = None
            root.destroy()
            return
        action, duration = steps[index]
        target = action()
        if target is not None:
            # 押すところを見せてから押す
            frames.append((grab(ring_on=target), 700))
            target.event_generate("<Button-1>")
            root.after(SETTLE_MS, lambda: run(index + 1))
            return
        shots = max(1, duration // FRAME_MS)

        def shoot(count: int) -> None:
            frames.append((grab(), FRAME_MS))
            if count + 1 < shots:
                root.after(FRAME_MS, lambda: shoot(count + 1))
            else:
                run(index + 1)

        shoot(0)

    root.after(SETTLE_MS, lambda: run(0))
    root.mainloop()
    save_gif(frames, out_path)


def draw_click(window: Image.Image, cx: int, cy: int) -> Image.Image:
    """押すところに、半透明の丸とマウスの矢印を描く（緑のボタンの上でも見えるよう、黒っぽい色にする）"""
    overlay = Image.new("RGBA", window.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    radius = round(14 * SCALE)
    circle = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(circle, fill=(0, 0, 0, 45), outline=(34, 34, 34, 200), width=2)
    # 矢印の先を、押すところに合わせる
    arrow = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
    points = [(cx + round(px * SCALE), cy + round(py * SCALE)) for px, py in arrow]
    draw.polygon(points, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
    return Image.alpha_composite(window.convert("RGBA"), overlay).convert("RGB")


def save_gif(frames: list[tuple[Image.Image, int]], out_path: Path) -> None:
    """続けて同じ画面のコマはまとめ、全部のコマで同じ色の組（パレット）を使って GIF にする"""
    merged: list[tuple[Image.Image, int]] = []
    for image, duration in frames:
        if merged and image.tobytes() == merged[-1][0].tobytes():
            merged[-1] = (merged[-1][0], merged[-1][1] + duration)
        else:
            merged.append((image, duration))
    # 色の組は、全部のコマを並べた画像から作る（コマごとに作ると、色が少しずつ変わってちらつく）
    sample = Image.new("RGB", (CANVAS_SIZE[0], CANVAS_SIZE[1] * len(merged)))
    for number, (image, _) in enumerate(merged):
        sample.paste(image, (0, CANVAS_SIZE[1] * number))
    palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    images = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image, _ in merged]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        duration=[duration for _, duration in merged],
        loop=0,
        optimize=True,
    )
    print(f"{out_path}（{len(images)}コマ・{out_path.stat().st_size // 1024}KB）")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_DIR / "docs" / "demo.gif")
