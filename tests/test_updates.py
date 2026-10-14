import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from justdoit import updates  # noqa: E402


def fake_response(data: dict):
    response = io.BytesIO(json.dumps(data).encode("utf-8"))
    response.__enter__ = lambda self=response: self
    response.__exit__ = lambda *args: None
    return response


class VersionTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v1.2.0"), (1, 2, 0))
        self.assertEqual(updates.parse_version("1.10"), (1, 10))
        self.assertIsNone(updates.parse_version("latest"))
        self.assertIsNone(updates.parse_version("v1.2.0-beta"))

    def test_is_newer_compares_numbers_not_text(self):
        self.assertTrue(updates.is_newer("1.10.0", current="1.9.0"))  # 文字として比べると逆になる
        self.assertTrue(updates.is_newer("v1.2.1", current="1.2.0"))
        self.assertTrue(updates.is_newer("1.3", current="1.2.9"))
        self.assertFalse(updates.is_newer("1.2.0", current="1.2.0"))
        self.assertFalse(updates.is_newer("1.2", current="1.2.0"))
        self.assertFalse(updates.is_newer("1.1.0", current="1.2.0"))
        self.assertFalse(updates.is_newer("nightly", current="1.2.0"))


class CheckForUpdateTest(unittest.TestCase):
    def test_returns_release_when_newer(self):
        data = {"tag_name": "v9.0.0", "html_url": "https://github.com/example/releases/tag/v9.0.0"}
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=fake_response(data)):
            release = updates.check_for_update()
        self.assertEqual(release, updates.Release("9.0.0", "https://github.com/example/releases/tag/v9.0.0"))

    def test_returns_none_when_up_to_date(self):
        data = {"tag_name": f"v{updates.__version__}", "html_url": "https://example.com"}
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=fake_response(data)):
            self.assertIsNone(updates.check_for_update())

    def test_returns_none_when_offline_or_broken(self):
        with mock.patch.object(updates.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            self.assertIsNone(updates.check_for_update())
        broken = fake_response({"message": "rate limited"})
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=broken):
            self.assertIsNone(updates.check_for_update())


if __name__ == "__main__":
    unittest.main()
