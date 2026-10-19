# CLAUDE.md

Claude Code でこのリポジトリを開発するときの決まりごと。アプリの説明・構成・コマンドは [README.md](README.md) の「開発者向け」にある。

## プロジェクトについて

- 「Just do it.」：ポモドーロ＋作業記録のデスクトップアプリ（Python 3.12+ / Tkinter、Windows・macOS）と、週次レポート・同期の配信サービス（Google Apps Script、`gas/report_service/`）
- 就職活動のポートフォリオで、利用者は本人と知り合い数人。コードの読みやすさと README の分かりやすさも成果物の一部
- アプリのコンセプトは「シンプルで作業の邪魔をしない」。メインメニューの項目は増やさず、設定も最小限にする
- 費用はかけない（有料のサービス・ツールは使わない）

## やりとり

- 日本語で答える。ブラウザや GitHub Desktop などの画面操作は、押すボタン名まで書いた具体的な手順にする
- 画面の見た目・使い心地は、ユーザーが自分で Windows / macOS で動かして確かめる。確かめてほしい点を箇条書きで渡す

## Git とリリース

- 変更ごとにブランチを作り、Claude はローカルでコミットまで行う。push・プルリクエスト・main への取り込みは、ユーザーが GitHub Desktop と GitHub の画面で行う
- コミットメッセージは日本語で、何をなぜ変えたかを書く
- 利用者に関わる変更は [CHANGELOG.md](CHANGELOG.md) の「未リリース」に書く（リリースノートになる）
- リリースのタグは、ユーザーが GitHub の Releases →「Draft a new release」で作る（コマンドで作ったタグは GitHub Desktop が push しない）。手順は README の「リリース」

## コミット前の確認

次をすべて通してから「できた」と言う。

```bash
python -m ruff check .
python -m mypy
python -m mypy --platform win32
python -m mypy --platform darwin
python -m mypy --platform linux
python -m unittest discover -s tests
node gas/tests/run.js
```

- **mypy は3つの OS すべてで確かめる**。OS ごとの分岐は `sys.platform == "win32"` / `"darwin"` で書く（`platform.system()` だと mypy が見分けられず、v1.4.0 で CI が失敗した）
- **画面・依存ライブラリ・`JustDoIt.spec` を変えたら、ビルドしたアプリでも確かめる**。`python main.py` で動いても、配布版だけ壊れることがある（v1.1.0〜v1.2.0 で、同梱する matplotlib のフォントを削ったため振り返りのグラフが出なかった）

  ```bash
  python -m PyInstaller --noconfirm --log-level ERROR JustDoIt.spec
  ```
  - macOS：`"dist/Just do it.app/Contents/MacOS/JustDoIt" --self-test`
  - Windows：`dist/JustDoIt/JustDoIt.exe --self-test`

  終了コードが 0 なら成功。結果は作業フォルダの `selftest.log` に出る。同梱するファイルは、`--self-test` を通さずに削らない
- **Windows の見た目は、GitHub Actions のスクリーンショットで確かめる**（手元に Windows の PC が無いため）。プルリクエストの Actions の実行ページの「Artifacts」に、`screenshots-Windows`（全画面のライト・ダーク）が保存される。手元では `--self-test --screenshots screenshots` で同じものが撮れる
- GAS（`gas/report_service/`）を変えたら、`node gas/tests/run.js` を通す。main に取り込むと `deploy-gas.yml` が自動でデプロイする（URL は変わらない）

## 気をつけること

- `config.json` と `log/` はコミットしない。ソースから起動したときの設定と記録で、週次レポートの認証トークンを含む（`.gitignore` 済み）
- 配信サービスの URL（`REPORT_SERVICE_URL`）を変えると、配布済みのアプリから届かなくなる。GAS は「デプロイを管理」で新バージョンにする（「新しいデプロイ」にしない）
- 記録の保存先フォルダ名とファイル名は `JustDoIt` のまま変えない（変えると、これまでの記録が見つからなくなる）
