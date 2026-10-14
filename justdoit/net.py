"""HTTPS 通信の共通処理

配布版（PyInstaller でビルドしたアプリ）の macOS では、Python がサーバーの証明書を確かめるための
ルート証明書の一覧を見つけられず、HTTPS の通信がすべて失敗する（CERTIFICATE_VERIFY_FAILED）。
そこで、OS の一覧に加えて、アプリに同梱した certifi の一覧も使う。
"""

from functools import lru_cache
import ssl
import urllib.error
import urllib.request


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """OS のルート証明書と certifi のルート証明書の両方を使う SSL の設定"""
    context = ssl.create_default_context()  # OS の一覧（Windows は OS の証明書ストア）
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass  # certifi が無くても、OS の一覧で通信できる環境ならそのまま使う
    return context


def urlopen(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())


def friendly_message(error: BaseException) -> str:
    """通信のエラーを、利用者がどうすればよいかわかる言葉にする（技術的な内容は error.log に残す）"""
    reason = getattr(error, "reason", None)
    if isinstance(error, urllib.error.HTTPError):
        return f"サーバーでエラーが起きました（{error.code}）。時間をおいて、もう一度お試しください。"
    # 証明書の確認の失敗は ValueError の仲間でもあるので、ValueError より先に調べる
    if isinstance(error, ssl.SSLError) or isinstance(reason, ssl.SSLError):
        return "安全な通信を確立できませんでした。PC の日付と時刻が正しいか確かめて、もう一度お試しください。"
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason):
        return "サーバーからの応答がありませんでした。時間をおいて、もう一度お試しください。"
    if isinstance(error, ValueError):  # 応答が JSON として読めない
        return "サーバーから予期しない応答がありました。時間をおいて、もう一度お試しください。"
    return "インターネットに接続できませんでした。接続を確かめて、もう一度お試しください。"


def root_certificate_count() -> int:
    """読み込めたルート証明書の数（配布版の動作確認で、0 になっていないか確かめる）"""
    return ssl_context().cert_store_stats()["x509_ca"]
