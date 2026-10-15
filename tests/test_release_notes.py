from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import release_notes  # noqa: E402

CHANGELOG = """# 変更履歴

## [未リリース]

### 追加
- まだリリースしていない変更

## [1.5.0] - 2026-10-16

### 追加
- 新しい機能

### 修正
- 直した不具合

## [1.4.0] - 2026-10-15

### 追加
- 前のバージョンの変更

[未リリース]: https://example.com/compare/v1.5.0...HEAD
[1.5.0]: https://example.com/compare/v1.4.0...v1.5.0
"""


class ReleaseNotesTest(unittest.TestCase):
    def test_extracts_only_that_version(self):
        notes = release_notes.extract(CHANGELOG, "1.5.0")
        self.assertEqual(notes, "### 追加\n- 新しい機能\n\n### 修正\n- 直した不具合")

    def test_last_version_stops_before_links(self):
        self.assertEqual(release_notes.extract(CHANGELOG, "1.4.0"), "### 追加\n- 前のバージョンの変更")

    def test_missing_version_is_an_error(self):
        # 変更履歴を書き忘れたままリリースしないよう、見つからなければ止める
        with self.assertRaises(ValueError):
            release_notes.extract(CHANGELOG, "1.6.0")
        with self.assertRaises(ValueError):
            release_notes.extract(CHANGELOG, "1.5")  # 1.5.0 と取り違えない

    def test_notes_link_to_the_changelog_of_that_tag(self):
        notes = release_notes.release_notes(CHANGELOG, "1.5.0")
        self.assertTrue(notes.endswith("/blob/v1.5.0/CHANGELOG.md) をご覧ください。\n"))

    def test_real_changelog_has_every_released_version(self):
        # 実際の CHANGELOG.md で、リリース済みのバージョンがすべて取り出せる
        text = release_notes.CHANGELOG.read_text(encoding="utf-8")
        for version in ("1.0.0", "1.2.2", "1.4.0"):
            self.assertTrue(release_notes.extract(text, version))


if __name__ == "__main__":
    unittest.main()
