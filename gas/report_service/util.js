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
  } else if (sheet.getLastColumn() < SHEET_HEADERS[name].length) {
    // 列を追加したバージョンへ更新したとき、既存のシートの見出しを補う
    sheet.getRange(1, 1, 1, SHEET_HEADERS[name].length).setValues([SHEET_HEADERS[name]]);
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

// row 行の column 列から右へ、書式なしテキストとして値を書き込む
function writeTextValues_(sheet, row, column, values) {
  sheet
    .getRange(row, column, 1, values.length)
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

// その利用者の記録に log_id が同じものがあるか
function hasLog_(sheet, userId, logId) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2 || sheet.getLastColumn() < LOG_ID_COLUMN) {
    return false;
  }
  return sheet
    .getRange(2, LOG_ID_COLUMN, lastRow - 1, 1)
    .createTextFinder(logId)
    .matchEntireCell(true)
    .findAll()
    .some((cell) => String(sheet.getRange(cell.getRow(), 1).getValue()) === userId);
}

// 利用者の記録の行番号を探す（見つからなければ 0）
// log_id で探し、ID のない古い記録は日時・作業内容・時間がすべて同じ行を探す
function findLogRow_(sheet, userId, logId, log) {
  const task = escapeFormula_(log.task);
  const index = getSheetRows_(sheet).findIndex((row) => {
    if (String(row[0]) !== userId) {
      return false;
    }
    if (logId && String(row[LOG_ID_COLUMN - 1]) === logId) {
      return true;
    }
    return (
      !row[LOG_ID_COLUMN - 1] &&
      String(row[1]) === log.datetime &&
      String(row[2]) === task &&
      Number(row[3]) === log.minutes
    );
  });
  return index === -1 ? 0 : index + 2;
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

// escapeFormula_ で付けた先頭の「'」を外して、アプリで入力したとおりの作業内容に戻す
function unescapeFormula_(text) {
  return /^'[=+\-@]/.test(text) ? text.slice(1) : text;
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
  return formatDateTime_(new Date());
}

function formatDateTime_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
}

function formatDay_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone(), "M/d");
}

function weekdayLabel_(date) {
  return WEEKDAYS[(date.getDay() + 6) % 7];
}

// 「1時間 20分」の形にする（1時間未満は「41分」、ちょうどの時間は「2時間」）
function formatHoursMins_(totalMins) {
  const hours = Math.floor(totalMins / 60);
  const mins = totalMins % 60;
  if (hours === 0) return mins + "分";
  return mins === 0 ? hours + "時間" : hours + "時間 " + mins + "分";
}

function formatDiff_(diffMins) {
  if (diffMins > 0) return "+" + formatHoursMins_(diffMins);
  if (diffMins < 0) return "-" + formatHoursMins_(Math.abs(diffMins));
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
