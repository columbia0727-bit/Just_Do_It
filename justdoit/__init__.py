"""Just do it. ポモドーロ＆作業記録デスクトップアプリ

- config / records / report_service / sync / updates / notify / net : 画面を持たない処理（単体テストの対象）
- ui                                                    : Tkinter の画面
- selftest                                              : ビルドしたアプリの動作確認（--self-test）
"""

# アプリのバージョン。リリースするときは、作るタグ（v1.2.0 など）と同じ番号にする
# （GitHub Actions がタグと一致しているか確かめ、違えばビルドを止める）
__version__ = "1.6.0"
