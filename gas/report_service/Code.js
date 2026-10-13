/**
 * Just do it. 週次レポート配信サービス
 *
 * 開発者が1つだけデプロイする共用の GAS Webアプリ。
 * 利用者はアプリにメールアドレスを登録するだけで、毎週月曜に先週のレポートが届く。
 *
 * スプレッドシートに自動作成されるシート
 *   users  : user_id, email, status(active / unsubscribed), created_at
 *   tokens : token_hash, user_id, created_at  … アプリ（端末）ごとの認証トークン（ハッシュのみ保存）
 *   logs   : user_id, datetime, task, minutes … LOG_RETENTION_DAYS より古い記録は自動削除
 *
 * @OnlyCurrentDoc  スプレッドシートの権限を、このスクリプトが紐づくシートだけに限定する
 */

const SHEET_HEADERS = {
  users: ["user_id", "email", "status", "created_at"],
  tokens: ["token_hash", "user_id", "created_at"],
  logs: ["user_id", "datetime", "task", "minutes"],
};

const CODE_TTL_SECONDS = 10 * 60;
const CODE_RESEND_SECONDS = 60;
const MAX_CODE_ATTEMPTS = 5;
const MAX_CODES_PER_EMAIL = 5; // CODE_LIMIT_WINDOW_SECONDS あたり
const CODE_LIMIT_WINDOW_SECONDS = 6 * 60 * 60;
const MIN_QUOTA_FOR_CODES = 20; // 週次レポート用に残しておく送信枠
const LOG_RETENTION_DAYS = 35;
const MAX_EMAIL_LENGTH = 200;
const MAX_TASK_LENGTH = 100;
const MAX_DURATION_MINUTES = 24 * 60;
const LOCK_TIMEOUT_MS = 10 * 1000;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;


// ==========================================
// アプリからのリクエスト窓口
// ==========================================
function doPost(e) {
  let data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return jsonResponse_({ status: "error", code: "invalid", message: "不正なリクエストです" });
  }

  const handlers = {
    register: handleRegister_,
    verify: handleVerify_,
    log: handleLog_,
    unregister: handleUnregister_,
  };
  const handler = handlers[data.action];
  if (!handler) {
    return jsonResponse_({ status: "error", code: "invalid", message: "不明な操作です" });
  }

  try {
    return jsonResponse_(withLock_(() => handler(data)));
  } catch (err) {
    return jsonResponse_({ status: "error", code: err.code || "error", message: err.message });
  }
}

function doGet(e) {
  const params = (e && e.parameter) || {};
  if (params.action === "unsubscribe") {
    // メールのリンク先で即停止すると、リンクを先読みするメールソフトで勝手に停止されるため、確認ボタンを挟む
    const template = HtmlService.createTemplate(UNSUBSCRIBE_HTML);
    template.uid = params.uid || "";
    template.sig = params.sig || "";
    return template.evaluate().setTitle("配信停止 | Just do it.");
  }
  return ContentService.createTextOutput("Just do it. report service is running.");
}

// 配信停止ページのボタンから google.script.run で呼ばれる
function confirmUnsubscribe(userId, sig) {
  if (!userId || sign_(String(userId)) !== sig) {
    throw new Error("配信停止リンクが正しくありません");
  }
  withLock_(() => deactivateUser_(String(userId)));
}


// ==========================================
// 各操作
// ==========================================

// メールアドレスに確認コードを送る
function handleRegister_(data) {
  const email = normalizeEmail_(data.email);
  const cache = CacheService.getScriptCache();

  if (cache.get("resend:" + email)) {
    fail_("確認コードは送信済みです。1分ほど待ってから再度お試しください", "rate_limited");
  }
  const sentCount = Number(cache.get("count:" + email) || 0);
  if (sentCount >= MAX_CODES_PER_EMAIL) {
    fail_("確認コードの送信回数が上限に達しました。時間をおいて再度お試しください", "rate_limited");
  }
  if (MailApp.getRemainingDailyQuota() < MIN_QUOTA_FOR_CODES) {
    fail_("現在混み合っています。明日以降に再度お試しください", "rate_limited");
  }

  const code = String(Math.floor(Math.random() * 1000000)).padStart(6, "0");
  cache.put(
    "code:" + email,
    JSON.stringify({ code: code, attempts: 0, expiresAt: Date.now() + CODE_TTL_SECONDS * 1000 }),
    CODE_TTL_SECONDS
  );
  cache.put("resend:" + email, "1", CODE_RESEND_SECONDS);
  cache.put("count:" + email, String(sentCount + 1), CODE_LIMIT_WINDOW_SECONDS);

  MailApp.sendEmail({
    to: email,
    name: "Just do it.",
    subject: "【Just do it.】確認コード: " + code,
    body:
      "「Just do it.」の週次レポート登録用の確認コードです。\n\n" +
      "確認コード: " + code + "\n\n" +
      "アプリの入力欄にこのコードを入力してください（" + CODE_TTL_SECONDS / 60 + "分間有効）。\n" +
      "心当たりがない場合は、このメールを破棄してください。",
  });
  return { status: "success" };
}

// 確認コードを照合し、アプリ用のトークンを発行する
function handleVerify_(data) {
  const email = normalizeEmail_(data.email);
  const cache = CacheService.getScriptCache();
  const key = "code:" + email;
  const raw = cache.get(key);
  if (!raw) {
    fail_("確認コードの有効期限が切れています。もう一度コードを送信してください", "expired");
  }

  const pending = JSON.parse(raw);
  if (String(data.code || "").trim() !== pending.code) {
    pending.attempts += 1;
    if (pending.attempts >= MAX_CODE_ATTEMPTS) {
      cache.remove(key);
      fail_("確認コードを規定回数以上間違えました。もう一度コードを送信してください", "expired");
    }
    const remainingSeconds = Math.max(1, Math.round((pending.expiresAt - Date.now()) / 1000));
    cache.put(key, JSON.stringify(pending), remainingSeconds);
    fail_("確認コードが正しくありません", "invalid_code");
  }
  cache.remove(key);

  const userId = activateUser_(email);
  const token = Utilities.getUuid().replace(/-/g, "") + Utilities.getUuid().replace(/-/g, "");
  appendTextRow_(getSheet_("tokens"), [sha256Hex_(token), userId, nowString_()]);
  return { status: "success", token: token };
}

// 作業記録を1件保存する
function handleLog_(data) {
  const userId = authenticate_(data.token);

  const datetime = String(data.datetime || "");
  if (!DATETIME_PATTERN.test(datetime)) {
    fail_("日時の形式が正しくありません", "invalid");
  }
  const task = String(data.task || "").trim().slice(0, MAX_TASK_LENGTH);
  if (!task) {
    fail_("作業内容が空です", "invalid");
  }
  const minutes = parseInt(data.minutes, 10);
  if (!(minutes >= 1 && minutes <= MAX_DURATION_MINUTES)) {
    fail_("実施時間が正しくありません", "invalid");
  }

  appendTextRow_(getSheet_("logs"), [userId, datetime, escapeFormula_(task), minutes]);
  return { status: "success" };
}

// アプリから配信を停止する
function handleUnregister_(data) {
  deactivateUser_(authenticate_(data.token));
  return { status: "success" };
}


// ==========================================
// 週次レポート（毎週月曜 9時台にトリガーで実行）
// ==========================================
function sendWeeklyReports() {
  const week = getLastWeekRange_(new Date());

  // 送信中に記録の受付を止めないよう、ロックはデータの読み込み時だけ取る
  const snapshot = withLock_(() => ({
    users: getSheetRows_(getSheet_("users")).filter((row) => row[2] === "active"),
    logsByUser: groupLogsByUser_(getSheetRows_(getSheet_("logs")), week.prevStart, week.end),
  }));

  const baseUrl = ScriptApp.getService().getUrl();
  let sent = 0;
  for (const [userId, email] of snapshot.users) {
    if (MailApp.getRemainingDailyQuota() < 1) {
      console.warn("送信上限に達したため、残りのレポートを送信できませんでした");
      break;
    }
    const logs = snapshot.logsByUser[userId] || [];
    const current = summarize_(logs, week.start, week.end);
    const previous = summarize_(logs, week.prevStart, week.start);
    try {
      MailApp.sendEmail({
        to: email,
        name: "Just do it.",
        subject: "【Just do it.】先週の作業レポート（" + formatDay_(week.start) + "〜" + formatDay_(week.lastDay) + "）",
        body: buildReportBody_(week, current, previous, unsubscribeUrl_(baseUrl, userId)),
      });
      sent++;
    } catch (err) {
      console.error("レポート送信に失敗しました: " + userId + " " + err);
    }
  }
  console.log("週次レポートを送信しました: " + sent + " / " + snapshot.users.length + " 件");

  purgeOldLogs_();
}

// 週次レポートのトリガー（毎週月曜 9時台）を作成する。エディタから1回だけ実行する
function createWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (trigger.getHandlerFunction() === "sendWeeklyReports") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger("sendWeeklyReports")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(9)
    .create();
}

function buildReportBody_(week, current, previous, unsubscribeUrl) {
  const lines = [
    "先週（" + formatDay_(week.start) + "〜" + formatDay_(week.lastDay) + "）の「Just do it.」レポートをお届けします。",
    "",
    "----------------------------------------",
    "",
    "[先週のサマリー]",
    "- 総作業時間 : " + formatHoursMins_(current.totalMinutes) +
      "（前の週より " + formatDiff_(current.totalMinutes - previous.totalMinutes) + "）",
    "- 記録回数 : " + current.count + "回",
    "- 記録した日 : " + current.days + " / 7日",
    "",
    "[作業内容別内訳]",
  ];

  const tasks = Object.keys(current.taskMap).sort((a, b) => current.taskMap[b] - current.taskMap[a]);
  if (tasks.length === 0) {
    lines.push("- 先週の記録はありませんでした。");
  }
  tasks.forEach((task) => {
    const mins = current.taskMap[task];
    const percentage = Math.round((mins / current.totalMinutes) * 100);
    lines.push("- " + task + " : " + formatHoursMins_(mins) + "（" + percentage + "%）");
  });

  lines.push(
    "",
    cheerMessage_(current, previous),
    "",
    "----------------------------------------",
    "※このメールは「Just do it.」アプリの週次レポート登録者に自動送信しています。",
    "配信停止はこちら: " + unsubscribeUrl
  );
  return lines.join("\n");
}

function cheerMessage_(current, previous) {
  if (current.totalMinutes === 0) {
    return "先週は記録がありませんでした。今週はまず「🔥 5分やる」から始めてみましょう！";
  }
  if (current.totalMinutes > previous.totalMinutes) {
    return "前の週より積み上がっています！この調子で今週も続けましょう。";
  }
  return "今週も5分から積み上げていきましょう。続けることがいちばんの力です。";
}


// ==========================================
// 利用者・トークン
// ==========================================
function authenticate_(token) {
  if (!token) {
    fail_("認証に失敗しました。設定画面から再登録してください", "unauthorized");
  }
  const tokens = getSheet_("tokens");
  const row = findRow_(tokens, 1, sha256Hex_(String(token)));
  if (!row) {
    fail_("認証に失敗しました。設定画面から再登録してください", "unauthorized");
  }
  return String(tokens.getRange(row, 2).getValue());
}

// メールアドレスの利用者を有効化し、user_id を返す（未登録なら新規作成）
function activateUser_(email) {
  const users = getSheet_("users");
  const row = findRow_(users, 2, email);
  if (row) {
    users.getRange(row, 3).setValue("active");
    return String(users.getRange(row, 1).getValue());
  }
  const userId = Utilities.getUuid();
  appendTextRow_(users, [userId, email, "active", nowString_()]);
  return userId;
}

// 配信を停止し、その利用者のトークンと作業記録を削除する
function deactivateUser_(userId) {
  const users = getSheet_("users");
  const row = findRow_(users, 1, userId);
  if (row) {
    users.getRange(row, 3).setValue("unsubscribed");
  }
  keepRows_(getSheet_("tokens"), (r) => String(r[1]) !== userId);
  keepRows_(getSheet_("logs"), (r) => String(r[0]) !== userId);
}

function purgeOldLogs_() {
  const now = new Date();
  const cutoff = addDays_(new Date(now.getFullYear(), now.getMonth(), now.getDate()), -LOG_RETENTION_DAYS);
  withLock_(() =>
    keepRows_(getSheet_("logs"), (r) => {
      const date = parseLogDate_(r[1]);
      return date !== null && date >= cutoff;
    })
  );
}

function unsubscribeUrl_(baseUrl, userId) {
  return baseUrl + "?action=unsubscribe&uid=" + encodeURIComponent(userId) + "&sig=" + sign_(userId);
}

// 配信停止リンクの改ざん防止用署名（秘密鍵は初回に自動生成してスクリプトプロパティに保存）
function sign_(value) {
  const props = PropertiesService.getScriptProperties();
  let secret = props.getProperty("UNSUBSCRIBE_SECRET");
  if (!secret) {
    secret = Utilities.getUuid() + Utilities.getUuid();
    props.setProperty("UNSUBSCRIBE_SECRET", secret);
  }
  return toHex_(Utilities.computeHmacSha256Signature(value, secret));
}


// ==========================================
// 集計
// ==========================================
function getLastWeekRange_(now) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const thisMonday = addDays_(today, -((today.getDay() + 6) % 7));
  return {
    prevStart: addDays_(thisMonday, -14),
    start: addDays_(thisMonday, -7),
    end: thisMonday,
    lastDay: addDays_(thisMonday, -1),
  };
}

function groupLogsByUser_(rows, from, to) {
  const logsByUser = {};
  rows.forEach((row) => {
    const date = parseLogDate_(row[1]);
    if (date === null || date < from || date >= to) {
      return;
    }
    const userId = String(row[0]);
    (logsByUser[userId] = logsByUser[userId] || []).push({
      date: date,
      task: String(row[2]),
      minutes: Number(row[3]) || 0,
    });
  });
  return logsByUser;
}

function summarize_(logs, from, to) {
  const summary = { totalMinutes: 0, count: 0, days: 0, taskMap: {} };
  const daySet = {};
  logs.forEach((log) => {
    if (log.date < from || log.date >= to) {
      return;
    }
    summary.totalMinutes += log.minutes;
    summary.count++;
    summary.taskMap[log.task] = (summary.taskMap[log.task] || 0) + log.minutes;
    daySet[log.date.toDateString()] = true;
  });
  summary.days = Object.keys(daySet).length;
  return summary;
}


// ==========================================
// 共通処理
// ==========================================
function fail_(message, code) {
  const err = new Error(message);
  err.code = code;
  throw err;
}

function withLock_(fn) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(LOCK_TIMEOUT_MS)) {
    fail_("サーバーが混み合っています。時間をおいて再度お試しください", "busy");
  }
  try {
    return fn();
  } finally {
    lock.releaseLock();
  }
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function getSheet_(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    appendTextRow_(sheet, SHEET_HEADERS[name]);
  }
  return sheet;
}

function getSheetRows_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }
  return sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
}

// 日時や作業内容が日付・数値に自動変換されないよう、書式なしテキストとして1行追加する
function appendTextRow_(sheet, values) {
  if (sheet.getLastRow() >= sheet.getMaxRows()) {
    sheet.insertRowsAfter(sheet.getMaxRows(), 500);
  }
  sheet
    .getRange(sheet.getLastRow() + 1, 1, 1, values.length)
    .setNumberFormat("@")
    .setValues([values.map(String)]);
}

// keep が true を返す行だけを残す
function keepRows_(sheet, keep) {
  const rows = getSheetRows_(sheet);
  const kept = rows.filter(keep);
  if (kept.length === rows.length) {
    return;
  }
  sheet.getRange(2, 1, rows.length, sheet.getLastColumn()).clearContent();
  if (kept.length > 0) {
    sheet.getRange(2, 1, kept.length, kept[0].length).setValues(kept);
  }
}

// column 列（1始まり）が value と完全一致する行番号を返す（見つからなければ 0）
function findRow_(sheet, column, value) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return 0;
  }
  const cell = sheet
    .getRange(2, column, lastRow - 1, 1)
    .createTextFinder(value)
    .matchEntireCell(true)
    .matchCase(true)
    .findNext();
  return cell ? cell.getRow() : 0;
}

function normalizeEmail_(value) {
  const email = String(value || "").trim().toLowerCase();
  if (email.length > MAX_EMAIL_LENGTH || !EMAIL_PATTERN.test(email)) {
    fail_("メールアドレスの形式が正しくありません", "invalid");
  }
  return email;
}

// 「=」などで始まる作業内容が数式として解釈されないようにする
function escapeFormula_(text) {
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function parseLogDate_(value) {
  if (value instanceof Date) {
    return isNaN(value.getTime()) ? null : value;
  }
  const m = String(value).match(DATETIME_PATTERN);
  if (!m) {
    return null;
  }
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]));
}

function addDays_(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

function nowString_() {
  return Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
}

function formatDay_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "M/d");
}

function formatHoursMins_(totalMins) {
  return Math.floor(totalMins / 60) + "時間 " + (totalMins % 60) + "分";
}

function formatDiff_(diffMins) {
  if (diffMins > 0) return "+" + diffMins + "分";
  if (diffMins < 0) return "-" + Math.abs(diffMins) + "分";
  return "±0分";
}

function sha256Hex_(text) {
  return toHex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8));
}

function toHex_(bytes) {
  return bytes.map((b) => ((b + 256) % 256).toString(16).padStart(2, "0")).join("");
}

const UNSUBSCRIBE_HTML = `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <base target="_top">
  </head>
  <body style="font-family: sans-serif; max-width: 480px; margin: 40px auto; padding: 0 16px; line-height: 1.7;">
    <h2>Just do it. 週次レポートの配信停止</h2>
    <p id="msg">配信を停止すると、サーバーに保存された作業記録も削除されます（アプリ内の記録は残ります）。</p>
    <button id="btn" data-uid="<?= uid ?>" data-sig="<?= sig ?>" style="padding: 8px 20px;">配信を停止する</button>
    <script>
      const btn = document.getElementById("btn");
      const msg = document.getElementById("msg");
      btn.addEventListener("click", () => {
        btn.disabled = true;
        google.script.run
          .withSuccessHandler(() => {
            msg.textContent = "配信を停止しました。ご利用ありがとうございました。";
            btn.remove();
          })
          .withFailureHandler((err) => {
            msg.textContent = err.message;
            btn.disabled = false;
          })
          .confirmUnsubscribe(btn.dataset.uid, btn.dataset.sig);
      });
    </script>
  </body>
</html>`;
