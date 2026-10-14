# -*- mode: python ; coding: utf-8 -*-
# アプリのビルド設定（pyinstaller --noconfirm JustDoIt.spec）
# ダウンロードを軽くするため、アプリで使わないライブラリ・データは同梱しない
from pathlib import Path
import re
import sys

# 利用者に見える名前。ファイル名・フォルダ名は "JustDoIt" のままにする
# （Windows は名前の最後の「.」を消してしまう。記録の保存先フォルダ名を変えると、これまでの記録が見つからなくなる）
DISPLAY_NAME = "Just do it."
FILE_NAME = "JustDoIt"
VERSION = re.search(r'__version__ = "([\d.]+)"', Path("justdoit/__init__.py").read_text(encoding="utf-8")).group(1)

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


def windows_version_info():
    """Windows の exe に埋め込む情報（タスクマネージャーやファイルのプロパティに表示される名前・バージョン）"""
    from PyInstaller.utils.win32 import versioninfo as vi

    numbers = tuple(int(part) for part in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))
    strings = [
        vi.StringStruct("FileDescription", DISPLAY_NAME),
        vi.StringStruct("ProductName", DISPLAY_NAME),
        vi.StringStruct("FileVersion", VERSION),
        vi.StringStruct("ProductVersion", VERSION),
        vi.StringStruct("OriginalFilename", f"{FILE_NAME}.exe"),
        vi.StringStruct("InternalName", FILE_NAME),
    ]
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            vi.StringFileInfo([vi.StringTable("041104B0", strings)]),  # 日本語・Unicode
            vi.VarFileInfo([vi.VarStruct("Translation", [0x0411, 1200])]),
        ],
    )


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
    name=FILE_NAME,
    console=False,
    # アイコンは PNG を渡すと PyInstaller が Pillow で .ico / .icns に変換する
    icon=["assets/icon.png"],
    version=windows_version_info() if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=FILE_NAME)
if sys.platform == "darwin":
    # メニューバー・Dock には CFBundleName が表示される。アプリのファイル名は最後の「.」を付けられないので
    # 「Just do it.app」（Finder では「Just do it」）にする
    app = BUNDLE(
        coll,
        name="Just do it.app",
        icon="assets/icon.png",
        bundle_identifier="io.github.columbia0727-bit.justdoit",
        info_plist={
            "CFBundleName": DISPLAY_NAME,
            "CFBundleDisplayName": DISPLAY_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
        },
    )
