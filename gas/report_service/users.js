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

// メールアドレスの利用者を有効化し、{ userId, schedule } を返す（未登録なら新規作成）
// schedule が null なら、登録済みの利用者は以前のタイミング、新規の利用者は既定のタイミングにする
function activateUser_(email, schedule) {
  const users = getSheet_("users");
  const row = findRow_(users, 2, email);
  if (!row) {
    const userId = Utilities.getUuid();
    const newSchedule = schedule || DEFAULT_SCHEDULE;
    appendTextRow_(
      users,
      [userId, email, "active", nowString_()].concat(scheduleValues_(newSchedule, new Date(), null))
    );
    return { userId: userId, schedule: newSchedule };
  }

  users.getRange(row, 3).setValue("active");
  const saved = users.getRange(row, USER_SCHEDULE_COLUMN, 1, 2).getValues()[0];
  const newSchedule = schedule || normalizeSchedule_(saved[0], saved[1]);
  // 停止していた間に next_report_at が過ぎていても、すぐには送らないよう計算し直す
  writeSchedule_(users, row, newSchedule);
  return { userId: String(users.getRange(row, 1).getValue()), schedule: newSchedule };
}

// 届くタイミングを保存し、次に届ける日時を計算し直す
function writeSchedule_(users, row, schedule) {
  const lastReportAt = parseLogDate_(users.getRange(row, USER_SCHEDULE_COLUMN + 3).getValue());
  writeTextValues_(users, row, USER_SCHEDULE_COLUMN, scheduleValues_(schedule, new Date(), lastReportAt));
}

// users シートの report_weekday 〜 last_report_at に書き込む値
function scheduleValues_(schedule, now, lastReportAt) {
  return [
    schedule.weekday,
    schedule.hour,
    formatDateTime_(nextReportAt_(schedule, now, lastReportAt)),
    lastReportAt ? formatDateTime_(lastReportAt) : "",
  ];
}

// 次に届ける日時: now より後で、前回のレポートから MIN_REPORT_INTERVAL_DAYS 以上空いた、最初の「指定の曜日・時刻」
// （タイミングを変えた直後に、同じ週のレポートが2通届かないようにする）
function nextReportAt_(schedule, now, lastReportAt) {
  let after = now;
  if (lastReportAt) {
    const earliest = new Date(lastReportAt.getTime() + MIN_REPORT_INTERVAL_DAYS * 86400000);
    if (earliest > after) {
      after = earliest;
    }
  }
  const weekdayOfAfter = (after.getDay() + 6) % 7;
  const daysAhead = (schedule.weekday - weekdayOfAfter + 7) % 7;
  let next = new Date(after.getFullYear(), after.getMonth(), after.getDate() + daysAhead, schedule.hour);
  if (next <= after) {
    next = new Date(next.getFullYear(), next.getMonth(), next.getDate() + 7, schedule.hour);
  }
  return next;
}

// アプリから送られた weekday / hour を検証する（optional なら、どちらも無いとき null を返す）
function parseSchedule_(data, optional) {
  if (optional && data.weekday === undefined && data.hour === undefined) {
    return null;
  }
  const weekday = Number(data.weekday);
  const hour = Number(data.hour);
  const valid =
    Number.isInteger(weekday) && weekday >= 0 && weekday <= 6 &&
    Number.isInteger(hour) && hour >= MIN_REPORT_HOUR && hour <= MAX_REPORT_HOUR;
  if (!valid) {
    fail_("届くタイミングの指定が正しくありません", "invalid");
  }
  return { weekday: weekday, hour: hour };
}

// 週の目標（分）。アプリから送られた値を検証する（0 は目標なし）
function parseGoal_(value) {
  const minutes = Number(value);
  if (!Number.isInteger(minutes) || minutes < 0 || minutes > MAX_GOAL_MINUTES) {
    fail_("週の目標の指定が正しくありません", "invalid");
  }
  return minutes;
}

// シートに保存された週の目標（分）。空・不正な値は 0（目標なし）
function readGoal_(value) {
  const minutes = Number(value);
  return Number.isInteger(minutes) && minutes > 0 && minutes <= MAX_GOAL_MINUTES ? minutes : 0;
}

function writeGoal_(users, row, minutes) {
  writeTextValues_(users, row, USER_GOAL_COLUMN, [minutes]);
}

// シートに保存された値を { weekday, hour } にする（空の場合は既定のタイミング）
function normalizeSchedule_(weekday, hour) {
  if (weekday === "" || hour === "") {
    return DEFAULT_SCHEDULE;
  }
  return { weekday: Number(weekday), hour: Number(hour) };
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
  keepRows_(getSheet_("deleted"), (r) => String(r[0]) !== userId);
}

// 預かる日数を過ぎた記録と、消した記録の ID を削除する
function purgeOldLogs_() {
  const now = new Date();
  const cutoff = addDays_(new Date(now.getFullYear(), now.getMonth(), now.getDate()), -LOG_RETENTION_DAYS);
  const isRecent = (value) => {
    const date = parseLogDate_(value);
    return date !== null && date >= cutoff;
  };
  withLock_(() => {
    keepRows_(getSheet_("logs"), (r) => isRecent(r[1]));
    keepRows_(getSheet_("deleted"), (r) => isRecent(r[2]));
  });
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
