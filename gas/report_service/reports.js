// ==========================================
// 週次レポート（1時間ごとにトリガーで実行し、届ける時刻を過ぎた利用者にだけ送る）
// ==========================================
function sendDueReports() {
  const now = new Date();
  const due = withLock_(() => findDueUsers_(now));

  if (due.length > 0) {
    // 送信中に記録の受付を止めないよう、ロックはデータの読み書き時だけ取る
    const oldest = due.reduce((min, user) => (user.dueAt < min ? user.dueAt : min), now);
    const logsByUser = withLock_(() =>
      groupLogsByUser_(getSheetRows_(getSheet_("logs")), getReportRange_(oldest).yearStart, now)
    );

    const baseUrl = ScriptApp.getService().getUrl();
    const done = [];
    for (const user of due) {
      // 長く遅れたレポートは今さら届いても混乱するので、送らずに次の回へ回す
      if (now - user.dueAt > MAX_REPORT_DELAY_HOURS * 3600 * 1000) {
        done.push({ user: user, sent: false });
        continue;
      }
      // 送れなかった利用者は next_report_at を更新しないので、次の1時間後に再送される
      if (MailApp.getRemainingDailyQuota() < 1) {
        console.warn("送信上限に達したため、残りのレポートは次回送信します");
        break;
      }
      try {
        sendReport_(user, logsByUser[user.userId] || [], baseUrl);
        done.push({ user: user, sent: true });
      } catch (err) {
        console.error("レポート送信に失敗しました: " + user.userId + " " + err);
      }
    }

    withLock_(() => {
      const users = getSheet_("users");
      done.forEach(({ user, sent }) => {
        const row = findRow_(users, 1, user.userId);
        if (row) {
          const last = sent ? now : user.lastReportAt;
          writeTextValues_(users, row, USER_SCHEDULE_COLUMN + 2, [
            formatDateTime_(nextReportAt_(user.schedule, now, last)),
            last ? formatDateTime_(last) : "",
          ]);
        }
      });
    });
    console.log("レポートを送信しました: " + done.filter((d) => d.sent).length + " / " + due.length + " 件");
  }

  if (now.getHours() === PURGE_HOUR) {
    purgeOldLogs_();
  }
}

// next_report_at を過ぎた有効な利用者を返す（next_report_at が空の利用者は、ここで初期化する）
function findDueUsers_(now) {
  const users = getSheet_("users");
  const due = [];
  getSheetRows_(users).forEach((row, i) => {
    if (row[2] !== "active") {
      return;
    }
    const offset = USER_SCHEDULE_COLUMN - 1;
    const schedule = normalizeSchedule_(row[offset], row[offset + 1]);
    const dueAt = parseLogDate_(row[offset + 2]);
    const lastReportAt = parseLogDate_(row[offset + 3]);
    if (!dueAt) {
      // 時刻を選べるようになる前に登録した利用者（月曜 9時台のまま）
      writeTextValues_(users, i + 2, USER_SCHEDULE_COLUMN, scheduleValues_(schedule, now, lastReportAt));
      return;
    }
    if (dueAt <= now) {
      due.push({ userId: String(row[0]), email: String(row[1]), schedule, dueAt, lastReportAt });
    }
  });
  return due;
}

// isTest が true なら、件名に【テスト】を付ける（設定画面の「テストメールを送る」）
function sendReport_(user, logs, baseUrl, isTest) {
  // 集計期間は「届ける予定だった日時」から決める（送信が遅れても期間がずれないように）
  const report = buildReport_(logs, user.dueAt);
  const week = report.week;
  const unsubscribeUrl = unsubscribeUrl_(baseUrl, user.userId);
  MailApp.sendEmail({
    to: user.email,
    name: "Just do it.",
    subject:
      (isTest ? "【テスト】" : "") +
      "【Just do it.】1週間の作業レポート（" + formatDay_(week.start) + "〜" + formatDay_(week.lastDay) + "）",
    // HTML を表示できないメールソフト向けにテキスト版も付ける
    body: buildReportBody_(report, unsubscribeUrl),
    htmlBody: buildReportHtml_(report, unsubscribeUrl),
  });
}

// レポートのトリガー（1時間ごと）を作成する。エディタから1回だけ実行する
// （以前の「毎週月曜 9時台」のトリガーが残っていれば削除する）
function createReportTrigger() {
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (["sendWeeklyReports", "sendDueReports"].includes(trigger.getHandlerFunction())) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger("sendDueReports").timeBased().everyHours(1).create();
}

function buildReportBody_(report, unsubscribeUrl) {
  const { week, current, previous } = report;
  const lines = [
    "この1週間（" + formatDay_(week.start) + "〜" + formatDay_(week.lastDay) + "）の「Just do it.」レポートをお届けします。",
    "",
    cheerMessage_(report),
    "",
    "----------------------------------------",
    "",
    "[この1週間のサマリー]",
    "- 総作業時間 : " + formatHoursMins_(current.totalMinutes) +
      "（前の週より " + formatDiff_(current.totalMinutes - previous.totalMinutes) + "）",
    "- 記録回数 : " + current.count + "回",
    "- 記録した日 : " + current.days + " / 7日",
    "",
    "[これまでの積み上げ]",
    "- 直近30日 : " + formatHoursMins_(report.recent.totalMinutes),
    "- 直近12か月 : " + formatHoursMins_(monthsTotal_(report.months)),
    "",
    "[作業内容別内訳]",
  ];

  const tasks = Object.keys(current.taskMap).sort((a, b) => current.taskMap[b] - current.taskMap[a]);
  if (tasks.length === 0) {
    lines.push("- この1週間の記録はありませんでした。");
  }
  tasks.forEach((task) => {
    const mins = current.taskMap[task];
    const percentage = Math.round((mins / current.totalMinutes) * 100);
    lines.push("- " + task + " : " + formatHoursMins_(mins) + "（" + percentage + "%）");
  });

  lines.push(
    "",
    "----------------------------------------",
    "※このメールは「Just do it.」アプリの週次レポート登録者に自動送信しています。",
    "配信停止はこちら: " + unsubscribeUrl
  );
  return lines.join("\n");
}
