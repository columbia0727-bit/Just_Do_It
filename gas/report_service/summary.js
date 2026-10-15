// ==========================================
// 集計
// ==========================================
// レポートの集計期間（start 〜 lastDay の7日間）と、比較に使うその前の7日間（prevStart 〜）
// 朝・昼に届く場合は前日まで、夕方以降に届く場合はその日までを集計する
// （月曜 9時なら先週の月〜日、日曜 21時ならその週の月〜日）
// あわせて、アプリの振り返りの「月」「年」と同じ期間も返す
//   monthStart 〜：直近30日（1日ごと）　yearStart 〜：直近12か月（lastDay の月を含む12か月。1か月ごと）
function getReportRange_(sendAt) {
  const includesToday = sendAt.getHours() >= INCLUDE_TODAY_FROM_HOUR;
  const end = new Date(sendAt.getFullYear(), sendAt.getMonth(), sendAt.getDate() + (includesToday ? 1 : 0));
  const lastDay = addDays_(end, -1);
  return {
    yearStart: new Date(lastDay.getFullYear(), lastDay.getMonth() - (REPORT_MONTHS - 1), 1),
    monthStart: addDays_(end, -REPORT_RECENT_DAYS),
    prevStart: addDays_(end, -14),
    start: addDays_(end, -7),
    end: end,
    lastDay: lastDay,
  };
}

// レポートに載せる数字をまとめて計算する（この1週間・前の週・直近30日・直近12か月・週の目標）
function buildReport_(logs, dueAt, goalMinutes) {
  const week = getReportRange_(dueAt);
  return {
    goalMinutes: goalMinutes || 0,
    week: week,
    current: summarize_(logs, week.start, week.end),
    previous: summarize_(logs, week.prevStart, week.start),
    recent: summarize_(logs, week.monthStart, week.end),
    months: summarizeMonths_(logs, week.yearStart, week.end),
  };
}

// 1か月ごとの合計（yearStart の月から12か月分）。{ year, month, minutes } の配列
function summarizeMonths_(logs, yearStart, end) {
  const months = [];
  for (let i = 0; i < REPORT_MONTHS; i++) {
    const first = new Date(yearStart.getFullYear(), yearStart.getMonth() + i, 1);
    months.push({ year: first.getFullYear(), month: first.getMonth() + 1, minutes: 0 });
  }
  logs.forEach((log) => {
    if (log.date < yearStart || log.date >= end) {
      return;
    }
    const index =
      (log.date.getFullYear() - yearStart.getFullYear()) * 12 + (log.date.getMonth() - yearStart.getMonth());
    months[index].minutes += log.minutes;
  });
  return months;
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

// dayMinutes は from から1日ごとの合計（週なら [月, 火, …, 日] の7個）
function summarize_(logs, from, to) {
  const dayCount = Math.round((to - from) / 86400000);
  const summary = { totalMinutes: 0, count: 0, days: 0, taskMap: {}, dayMinutes: new Array(dayCount).fill(0) };
  logs.forEach((log) => {
    if (log.date < from || log.date >= to) {
      return;
    }
    summary.totalMinutes += log.minutes;
    summary.count++;
    summary.taskMap[log.task] = (summary.taskMap[log.task] || 0) + log.minutes;
    const dayIndex = Math.round((addDays_(log.date, 0) - from) / 86400000);
    summary.dayMinutes[dayIndex] += log.minutes;
  });
  summary.days = summary.dayMinutes.filter((mins) => mins > 0).length;
  return summary;
}
