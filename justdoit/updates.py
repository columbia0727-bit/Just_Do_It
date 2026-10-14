"""新しいバージョンが出ているかを、GitHub の最新リリースから確かめる

送るのは GitHub の公開 API へのリクエストだけで、記録や設定などの情報は送らない。
通信できないときや GitHub の応答がおかしいときは「わからない」（None）として扱い、アプリは止めない。
"""

from dataclasses import dataclass
import json
import re
import urllib.request

from justdoit import __version__

LATEST_RELEASE_API = "https://api.github.com/repos/columbia0727-bit/Just_Do_It/releases/latest"
RELEASES_PAGE = "https://github.com/columbia0727-bit/Just_Do_It/releases/latest"
TIMEOUT_SECONDS = 5


@dataclass
class Release:
    version: str  # "1.3.0"
    url: str  # リリースのページ


def parse_version(text: str) -> tuple[int, ...] | None:
    """"v1.2.0" や "1.2.0" を (1, 2, 0) にする（数字の並びでなければ None）"""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(latest: str, current: str = __version__) -> bool:
    """latest が current より新しいか（1.10.0 は 1.9.0 より新しい、のように数字で比べる）"""
    latest_parts, current_parts = parse_version(latest), parse_version(current)
    if latest_parts is None or current_parts is None:
        return False
    # 桁数が違っても比べられるよう、短いほうの末尾を 0 で埋める（1.2 → 1.2.0）
    width = max(len(latest_parts), len(current_parts))

    def padded(parts: tuple[int, ...]) -> tuple[int, ...]:
        return parts + (0,) * (width - len(parts))

    return padded(latest_parts) > padded(current_parts)


def fetch_latest_release() -> Release | None:
    """GitHub の最新リリースを返す（取得できなければ None）。時間がかかるので別スレッドから呼ぶ"""
    request = urllib.request.Request(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    tag = str(data.get("tag_name", ""))
    if parse_version(tag) is None:
        return None
    return Release(version=tag.lstrip("v"), url=str(data.get("html_url") or RELEASES_PAGE))


def check_for_update() -> Release | None:
    """今のバージョンより新しいリリースがあれば返す"""
    release = fetch_latest_release()
    return release if release and is_newer(release.version) else None
