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
  const hourKey = "codes:" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMddHH");
  const sentThisHour = Number(cache.get(hourKey) || 0);
  if (sentThisHour >= MAX_CODES_PER_HOUR) {
    fail_("現在混み合っています。1時間ほどしてから再度お試しください", "rate_limited");
  }
  if (MailApp.getRemainingDailyQuota() < MIN_QUOTA_FOR_CODES) {
    fail_("現在混み合っています。明日以降に再度お試しください", "rate_limited");
  }

  const code = generateCode_();
  cache.put(hourKey, String(sentThisHour + 1), 60 * 60);
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
      "「Just do it.」の週次レポートの登録（メールアドレスの変更）用の確認コードです。\n\n" +
      "確認コード: " + code + "\n\n" +
      "アプリの入力欄にこのコードを入力してください（" + CODE_TTL_SECONDS / 60 + "分間有効）。\n" +
      "心当たりがない場合は、このメールを破棄してください。",
  });
  return { status: "success" };
}

// 6桁の確認コード。Math.random() は推測されにくさが保証されないため、
// 安全な乱数から作られる UUID（バージョン4）の先頭48ビットから作る
function generateCode_() {
  const random = parseInt(Utilities.getUuid().replace(/-/g, "").slice(0, 12), 16);
  return String(random % 1000000).padStart(6, "0");
}

// 確認コードを照合し、アプリ用のトークンを発行する
// 届くタイミング（weekday / hour）が送られてきた場合は、その設定で登録する
function handleVerify_(data) {
  const email = normalizeEmail_(data.email);
  const schedule = parseSchedule_(data, true);
  consumeCode_(email, data.code);

  const user = activateUser_(email, schedule);
  const token = Utilities.getUuid().replace(/-/g, "") + Utilities.getUuid().replace(/-/g, "");
  appendTextRow_(getSheet_("tokens"), [sha256Hex_(token), user.userId, nowString_()]);
  return { status: "success", token: token, weekday: user.schedule.weekday, hour: user.schedule.hour };
}

// メールアドレスに送った確認コードを照合する（合っていればコードを使い切る。違えば fail_ で中断する）
function consumeCode_(email, codeValue) {
  const cache = CacheService.getScriptCache();
  const key = "code:" + email;
  const raw = cache.get(key);
  if (!raw) {
    fail_("確認コードの有効期限が切れています。もう一度コードを送信してください", "expired");
  }

  const pending = JSON.parse(raw);
  if (String(codeValue || "").trim() !== pending.code) {
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
}

// 登録中のメールアドレスを変える（新しいアドレスに register で送った確認コードで、受け取れることを確かめる）
// 利用者 ID はそのままなので、記録・届くタイミング・ほかの PC の登録は引き継がれる
function handleChangeEmail_(data) {
  const userId = authenticate_(data.token);
  const email = normalizeEmail_(data.email);
  const users = getSheet_("users");
  const row = findRow_(users, 1, userId);
  if (!row) {
    fail_("認証に失敗しました。設定画面から再登録してください", "unauthorized");
  }

  // 確認コードを使い切る前に確かめる（使えないアドレスなら、コードを無駄にしない）
  const other = findRow_(users, 2, email);
  if (other && other !== row && users.getRange(other, 3).getValue() === "active") {
    fail_("このメールアドレスは、別の登録で使われています", "email_in_use");
  }
  consumeCode_(email, data.code);

  users.getRange(row, 2).setValue(email);
  // 配信を停止した以前の登録が同じアドレスで残っていたら消す（アドレスで探すときに、こちらが見つかるように）
  if (other && other !== row) {
    users.deleteRow(other);
  }
  return { status: "success", email: email };
}

// 届くタイミングを変更する
function handleUpdateSchedule_(data) {
  const userId = authenticate_(data.token);
  const schedule = parseSchedule_(data, false);
  const users = getSheet_("users");
  const row = findRow_(users, 1, userId);
  if (!row) {
    fail_("認証に失敗しました。設定画面から再登録してください", "unauthorized");
  }
  writeSchedule_(users, row, schedule);
  return { status: "success", weekday: schedule.weekday, hour: schedule.hour };
}

// 作業記録を1件保存する
function handleLog_(data) {
  const userId = authenticate_(data.token);
  const log = parseLog_(data.datetime, data.task, data.minutes);

  // 通信の行き違いでアプリが同じ記録を再送してきた場合は、保存済みとして成功を返す
  // （ID を送らない古いアプリからの記録は、そのまま保存する）
  const logId = parseLogId_(data.id);
  const logs = getSheet_("logs");
  if (logId && hasLog_(logs, userId, logId)) {
    return { status: "success" };
  }

  appendTextRow_(logs, [userId, log.datetime, escapeFormula_(log.task), log.minutes, logId]);
  return { status: "success" };
}

// アプリの記録一覧で直した記録を、サーバー側でも直す
// 直す前の記録（id・datetime・task・minutes）で探し、new_datetime（省略時はそのまま）・new_task・new_minutes・new_id に書き換える
function handleUpdateLog_(data) {
  const userId = authenticate_(data.token);
  const before = parseLog_(data.datetime, data.task, data.minutes);
  const after = parseLog_(data.new_datetime || data.datetime, data.new_task, data.new_minutes);
  const logs = getSheet_("logs");
  const row = findLogRow_(logs, userId, parseLogId_(data.id), before);
  // 見つからない（保存期間を過ぎて削除済み・まだ届いていない等）なら、直すものがないので成功とする
  if (row) {
    writeTextValues_(logs, row, 2, [after.datetime, escapeFormula_(after.task), after.minutes, parseLogId_(data.new_id)]);
  }
  // 直す前の内容の記録は、ほかの PC からも消えるようにする
  markDeleted_(userId, parseLogId_(data.id));
  return { status: "success", updated: Boolean(row) };
}

// アプリの記録一覧で削除した記録を、サーバー側でも削除する
function handleDeleteLog_(data) {
  const userId = authenticate_(data.token);
  const log = parseLog_(data.datetime, data.task, data.minutes);
  const logs = getSheet_("logs");
  const row = findLogRow_(logs, userId, parseLogId_(data.id), log);
  if (row) {
    logs.deleteRow(row);
  }
  // 同期したときに、ほかの PC に残っている同じ記録も消えるようにする
  markDeleted_(userId, parseLogId_(data.id));
  return { status: "success", deleted: Boolean(row) };
}

function markDeleted_(userId, logId) {
  if (logId) {
    appendTextRow_(getSheet_("deleted"), [userId, logId, nowString_()]);
  }
}

// 同期: その利用者の記録・消した記録の ID・届くタイミングをまとめて返す
// アプリは、これを手元の記録と突き合わせて、足りない記録を加え、消された記録を消す
function handleSyncPull_(data) {
  const userId = authenticate_(data.token);
  const logs = getSheetRows_(getSheet_("logs"))
    .filter((row) => String(row[0]) === userId)
    .map(logForSync_)
    .filter((log) => log !== null);
  const deleted = getSheetRows_(getSheet_("deleted"))
    .filter((row) => String(row[0]) === userId)
    .map((row) => String(row[1]));

  const users = getSheet_("users");
  const row = findRow_(users, 1, userId);
  const saved = users.getRange(row, USER_SCHEDULE_COLUMN, 1, 2).getValues()[0];
  const schedule = normalizeSchedule_(saved[0], saved[1]);
  return {
    status: "success",
    // ほかの PC でメールアドレスを変えた場合に、この PC の表示も合わせる
    email: String(users.getRange(row, 2).getValue()),
    logs: logs,
    deleted: deleted,
    weekday: schedule.weekday,
    hour: schedule.hour,
    retention_days: LOG_RETENTION_DAYS,
  };
}

// logs シートの1行を、アプリと同じ形の記録にする（ID のない古い記録は、アプリと同じ計算で ID を作る）
function logForSync_(row) {
  const date = parseLogDate_(row[1]);
  const minutes = Number(row[3]);
  if (date === null || !(minutes >= 1)) {
    return null;
  }
  const datetime = formatDateTime_(date);
  const task = unescapeFormula_(String(row[2]));
  const id = String(row[LOG_ID_COLUMN - 1] || "") || sha256Hex_(datetime + "|" + task + "|" + minutes).slice(0, 32);
  return { datetime: datetime, task: task, minutes: minutes, id: id };
}

// アプリから送られた記録（日時・作業内容・時間）を検証する
function parseLog_(datetimeValue, taskValue, minutesValue) {
  const datetime = String(datetimeValue || "");
  if (!DATETIME_PATTERN.test(datetime)) {
    fail_("日時の形式が正しくありません", "invalid");
  }
  const task = String(taskValue || "").trim().slice(0, MAX_TASK_LENGTH);
  if (!task) {
    fail_("作業内容が空です", "invalid");
  }
  const minutes = parseInt(minutesValue, 10);
  if (!(minutes >= 1 && minutes <= MAX_DURATION_MINUTES)) {
    fail_("実施時間が正しくありません", "invalid");
  }
  return { datetime: datetime, task: task, minutes: minutes };
}

function parseLogId_(value) {
  return LOG_ID_PATTERN.test(String(value || "")) ? String(value) : "";
}

// 今の記録でレポートを1通、すぐに送る（登録後、最初のレポートを待たずに届くか確かめられるように）
function handleSendTestReport_(data) {
  const userId = authenticate_(data.token);
  const cache = CacheService.getScriptCache();
  if (cache.get("test:" + userId)) {
    fail_("テストメールは送信済みです。10分ほど待ってから再度お試しください", "rate_limited");
  }
  const dayKey = "tests:" + userId + ":" + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyyMMdd");
  const sentToday = Number(cache.get(dayKey) || 0);
  if (sentToday >= MAX_TEST_REPORTS_PER_DAY) {
    fail_("テストメールは1日" + MAX_TEST_REPORTS_PER_DAY + "回までです。明日以降に再度お試しください", "rate_limited");
  }
  if (MailApp.getRemainingDailyQuota() < MIN_QUOTA_FOR_CODES) {
    fail_("現在混み合っています。明日以降に再度お試しください", "rate_limited");
  }

  const users = getSheet_("users");
  const row = findRow_(users, 1, userId);
  if (!row) {
    fail_("認証に失敗しました。設定画面から再登録してください", "unauthorized");
  }
  const now = new Date();
  const user = { userId: userId, email: String(users.getRange(row, 2).getValue()), dueAt: now };
  const from = getReportRange_(now).yearStart;
  const logs = groupLogsByUser_(getSheetRows_(getSheet_("logs")), from, now)[userId] || [];

  cache.put("test:" + userId, "1", TEST_REPORT_INTERVAL_SECONDS);
  cache.put(dayKey, String(sentToday + 1), 24 * 60 * 60);
  sendReport_(user, logs, ScriptApp.getService().getUrl(), true);
  return { status: "success" };
}

// この PC だけ登録を解除する（この PC のトークンだけを消す。ほかの PC の同期・メール・サーバーの記録はそのまま）
function handleRemoveDevice_(data) {
  authenticate_(data.token);
  const tokenHash = sha256Hex_(String(data.token));
  keepRows_(getSheet_("tokens"), (r) => String(r[0]) !== tokenHash);
  return { status: "success" };
}

// アプリから配信を停止する（その利用者のすべての PC のトークンと、サーバーの記録をすべて消す）
function handleUnregister_(data) {
  deactivateUser_(authenticate_(data.token));
  return { status: "success" };
}
