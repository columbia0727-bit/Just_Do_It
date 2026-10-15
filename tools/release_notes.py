"""CHANGELOG.md から、指定したバージョンの変更点を取り出して、リリースノートにする

GitHub Actions がリリースのときに実行し、Release の説明文に使う（手で書き写す手間と、書き漏らしをなくすため）。

    python tools/release_notes.py 1.5.0 > notes.md
"""

import io
from pathlib import Path
import re
import sys

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
REPOSITORY_URL = "https://github.com/columbia0727-bit/Just_Do_It"


def extract(changelog: str, version: str) -> str:
    """「## [1.5.0] - 日付」の見出しから、次の「## [」の見出しの前までを返す（見つからなければ ValueError）"""
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", changelog, flags=re.M | re.S
    )
    if not match or not match.group(1).strip():
        raise ValueError(f"CHANGELOG.md に {version} の変更点がありません")
    return match.group(1).strip()


def release_notes(changelog: str, version: str) -> str:
    return (
        extract(changelog, version)
        + f"\n\nこれまでの変更点は [CHANGELOG.md]({REPOSITORY_URL}/blob/v{version}/CHANGELOG.md) をご覧ください。\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("使い方: python tools/release_notes.py 1.5.0", file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    try:
        notes = release_notes(CHANGELOG.read_text(encoding="utf-8"), version)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    # Windows で実行しても、日本語を UTF-8 で書き出す
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(notes, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
