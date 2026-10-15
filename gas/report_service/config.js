/**
 * Just do it. 週次レポート配信サービス
 *
 * 開発者が1つだけデプロイする共用の GAS Webアプリ。
 * 利用者はアプリにメールアドレスを登録するだけで、選んだ曜日・時刻に直近1週間のレポートが届く。
 * 同じメールアドレスで登録した PC 同士は、記録を同期できる（sync_pull で、その利用者の記録をまとめて返す）。
 *
 * 利用者ごとにトリガーを作るとトリガー数の上限に当たるため、トリガーは「1時間ごと」の1本だけにし、
 * 実行のたびに next_report_at を過ぎた利用者にだけ送る。
 *
 * スプレッドシートに自動作成されるシート
 *   users  : user_id, email, status(active / unsubscribed), created_at,
 *            report_weekday(0=月 … 6=日), report_hour, next_report_at, last_report_at,
 *            weekly_goal_minutes(週の目標。アプリの設定で選ぶ。0 または空なら目標なし)
 *   tokens : token_hash, user_id, created_at  … アプリ（端末）ごとの認証トークン（ハッシュのみ保存）
 *   logs   : user_id, datetime, task, minutes, log_id … LOG_RETENTION_DAYS より古い記録は自動削除
 *            log_id はアプリが記録の内容から作るID。再送された同じ記録を二重に保存しないためと、
 *            アプリの記録一覧で直した・消した記録をサーバー側で探すために使う
 *   deleted: user_id, log_id, deleted_at … 消した（直して別の内容になった）記録の ID。
 *            同期したときに、ほかの PC に残っている同じ記録も消すために使う
 *
 * 記録は、同期とレポートのために LOG_RETENTION_DAYS 日だけ預かる（配信を停止するとすぐに削除する）。
 *
 * ファイルの分け方（GAS では、すべてのファイルが同じ場所に読み込まれ、お互いの関数・定数を使える。
 * 読み込む順番は決まっていないので、ファイルの一番外側には、ほかのファイルの値を使わない定数と関数だけを書く）
 *   config.js   : 設定値（このファイル）       api.js     : アプリからのリクエストの窓口（doPost・doGet）
 *   handlers.js : 登録・記録・同期などの各操作  reports.js : 1時間ごとのトリガーと、レポートの送信
 *   mail.js     : レポートのメール（HTML・テキスト） cheer.js : レポートの「ひとこと」
 *   users.js    : 利用者・トークン               summary.js : 集計の期間と集計
 *   util.js     : 共通処理（シートの読み書き・日付など）
 * main に取り込むと、GitHub Actions が clasp でデプロイする（.github/workflows/deploy-gas.yml）。
 *
 * @OnlyCurrentDoc  スプレッドシートの権限を、このスクリプトが紐づくシートだけに限定する
 */

const SHEET_HEADERS = {
  users: [
    "user_id", "email", "status", "created_at",
    "report_weekday", "report_hour", "next_report_at", "last_report_at", "weekly_goal_minutes",
  ],
  tokens: ["token_hash", "user_id", "created_at"],
  logs: ["user_id", "datetime", "task", "minutes", "log_id"],
  deleted: ["user_id", "log_id", "deleted_at"],
};
const USER_SCHEDULE_COLUMN = 5; // report_weekday から last_report_at までの4列
const USER_GOAL_COLUMN = 9; // weekly_goal_minutes（週の目標。0 なら目標なし）
const MAX_GOAL_MINUTES = 100 * 60;
const LOG_ID_COLUMN = 5;

// レポートを届けるタイミング（アプリの設定画面で選ぶ）
const DEFAULT_SCHEDULE = { weekday: 0, hour: 9 }; // 月曜 9時台
const MIN_REPORT_HOUR = 6;
const MAX_REPORT_HOUR = 23;
const MAX_REPORT_DELAY_HOURS = 24; // 障害などでこれ以上遅れたレポートは送らず、次の回にする
const MIN_REPORT_INTERVAL_DAYS = 6; // タイミングを変えても、前のレポートからこの日数は空ける
const INCLUDE_TODAY_FROM_HOUR = 18; // この時刻以降に届くレポートは、その日の記録まで集計する
// レポートの「直近30日」「直近12か月」のグラフ（アプリの振り返りの「月」「年」と同じ期間）
const REPORT_RECENT_DAYS = 30;
const REPORT_MONTHS = 12;
const PURGE_HOUR = 4; // 古い記録の削除は1日1回、この時台に行う

const CODE_TTL_SECONDS = 10 * 60;
const CODE_RESEND_SECONDS = 60;
const MAX_CODE_ATTEMPTS = 5;
const MAX_CODES_PER_EMAIL = 5; // CODE_LIMIT_WINDOW_SECONDS あたり
const CODE_LIMIT_WINDOW_SECONDS = 6 * 60 * 60;
// 宛先を変えながら登録を繰り返されても送信枠を使い切られないよう、サービス全体でも上限を設ける
const MAX_CODES_PER_HOUR = 15;
const MIN_QUOTA_FOR_CODES = 20; // レポート用に残しておく送信枠（確認コード・テストメールはこれを残して送る）
// テストメール（アプリの設定画面から送る、その場で届くレポート）の回数制限
const TEST_REPORT_INTERVAL_SECONDS = 10 * 60;
const MAX_TEST_REPORTS_PER_DAY = 3;
// 記録を預かる日数。アプリの「年」の振り返り（直近12か月。12か月前の月の1日から、最大で約395日）が
// 同期した PC でもそろうよう、1年より少し長くする
const LOG_RETENTION_DAYS = 400;
const MAX_EMAIL_LENGTH = 200;
const MAX_TASK_LENGTH = 100;
const MAX_DURATION_MINUTES = 24 * 60;
const LOCK_TIMEOUT_MS = 10 * 1000;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
const LOG_ID_PATTERN = /^[0-9a-f]{32}$/;
