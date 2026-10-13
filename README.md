# Just do it. 🍅📊📈

> **「測る・記録する・分析する」をシームレスに繋ぐ、Python × クラウド連携型のポモドーロ＆作業記録デスクトップアプリ**

`Just do it.` は、日々の集中力維持と作業の振り返りを効率化するために開発した Windows / macOS 対応のデスクトップアプリです。
ポモドーロ・テクニックによる時間管理、ローカルとクラウド（Googleスプレッドシート）への二重記録、Gmail での週次レポート、そしてグラフによる振り返りまでをワンストップで実現します。

| メインメニュー | タイマー | ダッシュボード |
| :---: | :---: | :---: |
| ![メニュー](docs/menu.png) | ![タイマー](docs/timer.png) | ![ダッシュボード](docs/dashboard.png) |

---

## 📥 ダウンロード（Python 不要）

[Releases](../../releases) ページから OS に合ったファイルをダウンロードしてください。

| OS | ファイル | 起動方法 |
| --- | --- | --- |
| Windows | `JustDoIt-windows.zip` | 展開して `JustDoIt\JustDoIt.exe` をダブルクリック |
| macOS | `JustDoIt-macos.zip` | 展開して `JustDoIt.app` を「アプリケーション」へ移動 |

> **初回起動時の警告について**
> 本アプリはコード署名をしていないため、初回のみ OS の警告が表示されます。
> - **Windows**: 「Windows によって PC が保護されました」→「詳細情報」→「実行」
> - **macOS**: `JustDoIt.app` を右クリック →「開く」→「開く」

---

## 🌟 主な機能

### 1. 集中タイマー
- 🔥 **5分やる**：やる気が出ない時に「とりあえず取りかかる」ための短時間モード
- 🍅 **25分やる**：標準的なポモドーロ
- **休憩タイマー**：作業記録後、自動で最長10分の休憩タイマーへ移行
- **途中でやめる**：確認なしでそれまでの経過時間（1分単位で切り上げ）を記録してメニューへ戻る

### 2. 記録
- **自動ポップアップ入力**：タイマー終了時、ウィンドウが最前面に出て作業内容をすぐ入力できる
- **手動記録**：タイマーを使わなかった作業も後から追加（入力チェック付き・Enterキー対応）
- **二重バックアップ**
  - ローカル：CSV へ自動追記（`utf-8-sig` で Excel でも文字化けしない）
  - クラウド：Google Apps Script (GAS) 経由で Googleスプレッドシートへ送信（バックグラウンド通信で UI が固まらない）

### 3. 📊 ダッシュボード
- 作業内容別の時間割合（円グラフ）
- 直近14日間の日別作業時間（棒グラフ）
- 今日 / 直近7日 / 累計の作業時間サマリー

### 4. ☁️ クラウド連携＆週次レポート（任意）
- アプリ内の「⚙️ 設定」から GAS の WebアプリURL を登録するだけで連携 ON
- GAS の時間主導型トリガーで、毎週 Gmail に作業集計レポートを自動送信

---

## 💾 データの保存場所

| 実行方法 | 保存先 |
| --- | --- |
| Windows アプリ | `%APPDATA%\JustDoIt\` |
| macOS アプリ | `~/Library/Application Support/JustDoIt/` |
| ソースから実行 | `main.py` と同じフォルダ |

`log/work_log.csv`（作業ログ）と `config.json`（設定）が保存されます。保存先はアプリの「設定」画面でも確認できます。

---

## ☁️ Googleスプレッドシート連携の設定（任意）

1. Googleスプレッドシートを新規作成し、**「拡張機能」→「Apps Script」** を開く
2. [`gas/code.js`](gas/code.js) の内容をエディタに貼り付けて保存
3. **「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」**、アクセスできるユーザーを「全員」にしてデプロイ
4. 発行された URL（`https://script.google.com/macros/s/.../exec`）をアプリの **「⚙️ 設定」** に貼り付けて保存
5. 週次レポートを使う場合は、Apps Script エディタで `createWeeklyTrigger` を1回実行（毎週月曜9時台に送信）

> ⚠️ GAS のコードを修正したら「デプロイを管理」→「新バージョン」で再デプロイしないと反映されません。
> ⚠️ WebアプリURL を知っている人は誰でも書き込めるため、URL は公開しないでください（環境変数 `JUSTDOIT_GAS_URL` でも指定できます）。

---

## 🛠️ 開発者向け

### ソースから実行
```bash
pip install -r requirements.txt
python main.py
```

### テスト
```bash
python -m unittest discover -s tests -v
```

### アプリのビルド
```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm --windowed --name JustDoIt main.py
```
`dist/` に Windows なら `JustDoIt/JustDoIt.exe`、macOS なら `JustDoIt.app` が生成されます（各 OS 上でビルドする必要があります）。

`v1.0.0` のようなタグを push すると、GitHub Actions（[`.github/workflows/build.yml`](.github/workflows/build.yml)）がテスト → Windows / macOS 両方のビルド → Release への添付まで自動で行います。

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

### ディレクトリ構成
```
just-do-it/
├── main.py                    # アプリ本体（GUI・タイマー・記録・集計・ダッシュボード）
├── gas/code.js                # スプレッドシート連携・週次メールレポート用 GAS
├── tests/test_main.py         # 記録・集計ロジックの単体テスト
├── sample/work_log_sample.csv # ログ形式のサンプル
├── docs/                      # README 用スクリーンショット
├── requirements.txt
├── requirements-dev.txt       # ビルド用（PyInstaller）
└── .github/workflows/build.yml
```

---

## 🧩 工夫した点・苦労した点

- **通知を見逃さない UI**：タイマー終了時に入力ウィンドウを最前面（`-topmost`）かつモーダル（`grab_set()`）で開き、作業内容の記録漏れを防止
- **画面遷移とタイマーの整合性**：`after()` の予約IDを保持し、画面を切り替えるたびにキャンセルすることで、裏でタイマーが動き続ける不具合を解消
- **通信で UI を止めない**：GAS への送信を別スレッド＋タイムアウト付きで行い、ネットワークが遅くてもアプリが固まらない
- **GAS 連携のハマりどころ**：`doGet` 未定義によるエラーや、コード修正後に再デプロイしないと古い版が動き続ける問題を調査・解決
- **配布を見据えた設計**：ビルド後のアプリ内には書き込めないため、OS 標準のユーザーデータフォルダに保存先を切り替え。秘密情報（GAS URL）はコードから分離

---

## 🛠️ 技術スタック

- **言語**: Python 3.10+
- **GUI**: Tkinter
- **データ処理・可視化**: pandas, Matplotlib
- **クラウド**: Google Apps Script, Googleスプレッドシート, Gmail
- **配布**: PyInstaller, GitHub Actions
