# -*- mode: python ; coding: utf-8 -*-
# アプリのビルド設定（pyinstaller --noconfirm JustDoIt.spec）
# ダウンロードを軽くするため、アプリで使わないライブラリ・データは同梱しない
import sys

# 使わないライブラリ（開発環境に入っていると、pandas などに引きずられて同梱されてしまう）
EXCLUDES = [
    "scipy",
    "sklearn",
    "IPython",
    "pytest",
    "sqlite3",
    # 画像はアイコン（PNG）とグラフの表示にしか使わないので、他の画像形式のプラグインは不要
    "PIL._avif",
    "PIL.AvifImagePlugin",
    "PIL._webp",
    "PIL.WebPImagePlugin",
    "PIL._imagingcms",
    "PIL.ImageCms",
]


def is_needed_data(dest):
    """matplotlib の同梱データのうち、アプリで使わないものを除く"""
    dest = dest.replace("\\", "/")
    if "mpl-data/sample_data/" in dest:
        return False
    # PDF・PostScript への書き出し専用のフォントは使わない
    # （グラフの表示に使う fonts/ttf は残す。matplotlib は日本語を OS のフォントで描くときも、
    #   予備のフォント LastResortHE などを必ず読み込むため、削るとグラフが描けなくなる）
    if "mpl-data/fonts/afm/" in dest or "mpl-data/fonts/pdfcorefonts/" in dest:
        return False
    return True


a = Analysis(
    ["main.py"],
    datas=[("assets/icon.png", "assets")],
    excludes=EXCLUDES,
)
a.datas = [entry for entry in a.datas if is_needed_data(entry[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JustDoIt",
    console=False,
    # アイコンは PNG を渡すと PyInstaller が Pillow で .ico / .icns に変換する
    icon=["assets/icon.png"],
)
coll = COLLECT(exe, a.binaries, a.datas, name="JustDoIt")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="JustDoIt.app", icon="assets/icon.png")
