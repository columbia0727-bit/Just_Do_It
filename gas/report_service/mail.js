// ==========================================
// HTML メール（Gmail で崩れないよう、表とインラインスタイルだけで組む）
// ==========================================
const MAIL_COLORS = {
  accent: "#2f6f62",
  accentSoft: "#dbe9e5",
  text: "#222222",
  muted: "#8a8a86",
  border: "#e4e4e0",
  paper: "#f7f7f5",
};
const WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"];

function buildReportHtml_(report, unsubscribeUrl) {
  const c = MAIL_COLORS;
  const { week, current, previous } = report;
  const range = formatDay_(week.start) + "〜" + formatDay_(week.lastDay);
  const sections = [
    // ひとことは最初に目に入るよう、見出しのすぐ下に置く
    '<p style="margin:16px 0 0;padding-left:12px;border-left:3px solid ' + c.accent + ";font-size:15px;line-height:1.8;" +
      "color:" + c.text + ';">' + escapeHtml_(cheerMessage_(report)) + "</p>",
    htmlHero_(current, previous),
    htmlStats_(week, current),
    current.totalMinutes > 0 ? htmlDailyChart_(week, current) : "",
    current.totalMinutes > 0 ? htmlTaskBars_(current) : "",
    // 「これまでの積み上げ」は1週間の内容のあとに、小さめに添える（アプリの振り返りの「月」「年」と同じ期間）
    report.recent.totalMinutes > 0 ? htmlRecentChart_(week, report.recent) : "",
    monthsTotal_(report.months) > 0 ? htmlYearChart_(report.months) : "",
  ];

  return (
    '<div style="margin:0;padding:24px 12px;background:' + c.paper + ';">' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;' +
    "background:#ffffff;border-radius:12px;font-family:'Hiragino Sans','Yu Gothic UI','Meiryo',sans-serif;color:" + c.text + ';">' +
    '<tr><td style="padding:28px 28px 8px;">' +
    '<div style="font-size:13px;font-weight:bold;color:' + c.accent + ';">Just do it.</div>' +
    '<div style="margin-top:4px;font-size:20px;font-weight:bold;">1週間のレポート</div>' +
    '<div style="margin-top:2px;font-size:13px;color:' + c.muted + ';">' + range + "</div>" +
    "</td></tr>" +
    '<tr><td style="padding:8px 28px 28px;">' + sections.join("") + "</td></tr>" +
    "</table>" +
    '<p style="max-width:520px;margin:16px auto 0;font-size:11px;line-height:1.7;color:' + c.muted + ';text-align:center;">' +
    "このメールは「Just do it.」アプリの週次レポート登録者に自動送信しています。<br>" +
    '<a href="' + escapeHtml_(unsubscribeUrl) + '" style="color:' + c.muted + ';">配信を停止する</a></p>' +
    "</div>"
  );
}

// 合計時間を大きく、前の週との差を添える
function htmlHero_(current, previous) {
  const c = MAIL_COLORS;
  const diff = current.totalMinutes - previous.totalMinutes;
  let diffHtml = "";
  // 記録がなかった週は、前の週との差（マイナス）を見せて落ち込ませない
  if (current.totalMinutes > 0) {
    const up = diff > 0;
    diffHtml =
      '<span style="display:inline-block;margin-top:8px;padding:3px 10px;border-radius:999px;font-size:13px;' +
      "background:" + (up ? c.accentSoft : c.paper) + ";color:" + (up ? c.accent : c.muted) + ';">' +
      "前の週より " + formatDiff_(diff) + (up ? " ↑" : "") + "</span>";
  }
  return (
    '<div style="margin-top:16px;padding:20px;border-radius:10px;background:' + c.paper + ';text-align:center;">' +
    '<div style="font-size:13px;color:' + c.muted + ';">この1週間の作業時間</div>' +
    '<div style="margin-top:4px;font-size:34px;font-weight:bold;color:' + c.accent + ';">' +
    formatHoursMins_(current.totalMinutes) + "</div>" +
    diffHtml +
    "</div>"
  );
}

// 記録した日（7つの丸）・記録回数・一番がんばった日
function htmlStats_(week, current) {
  const c = MAIL_COLORS;
  const dots = current.dayMinutes
    .map((mins) =>
      '<span style="display:inline-block;width:12px;height:12px;margin-right:4px;border-radius:50%;background:' +
      (mins > 0 ? c.accent : c.border) + ';"></span>'
    )
    .join("");

  let bestHtml = "—";
  if (current.totalMinutes > 0) {
    const best = current.dayMinutes.indexOf(Math.max.apply(null, current.dayMinutes));
    const bestDay = addDays_(week.start, best);
    bestHtml =
      formatDay_(bestDay) + "（" + weekdayLabel_(bestDay) + "） " + formatHoursMins_(current.dayMinutes[best]);
  }

  // スマホでも崩れないよう、横に並べず「項目名｜値」の行にする
  const row = (label, value) =>
    "<tr>" +
    '<td style="padding:12px 0;border-bottom:1px solid ' + c.border + ";font-size:13px;color:" + c.muted + ';">' + label + "</td>" +
    '<td align="right" style="padding:12px 0;border-bottom:1px solid ' + c.border + ';font-size:15px;font-weight:bold;white-space:nowrap;">' +
    value + "</td></tr>";

  return (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;">' +
    row("記録した日", '<span style="margin-right:8px;">' + dots + "</span>" + current.days + " / 7日") +
    row("記録回数", current.count + "回") +
    row("一番がんばった日", bestHtml) +
    "</table>"
  );
}

// 曜日ごとの棒グラフ（棒の上に「25分」のように時間を出す）
function htmlDailyChart_(week, current) {
  // 届く曜日によって週の始まりが変わるので、曜日は日付から求める
  const labels = current.dayMinutes.map((_, i) => weekdayLabel_(addDays_(week.start, i)));
  return (
    htmlSectionTitle_("曜日ごとの作業時間") +
    htmlBarChart_(current.dayMinutes, labels, {
      height: 110,
      valueLabel: (mins) => (mins > 0 ? mins + "分" : ""),
    })
  );
}

// 直近30日の棒グラフ（1日ごと。日付は5日おきに出し、最新の日は必ず出す）
function htmlRecentChart_(week, recent) {
  const count = recent.dayMinutes.length;
  const labels = recent.dayMinutes.map((_, i) =>
    (count - 1 - i) % 5 === 0 ? formatDay_(addDays_(week.monthStart, i)) : ""
  );
  return (
    htmlSectionTitle_("直近30日", formatHoursMins_(recent.totalMinutes)) +
    htmlBarChart_(recent.dayMinutes, labels, { height: 70, gap: 1, labelSize: 10 })
  );
}

// 直近12か月の棒グラフ（1か月ごと）
function htmlYearChart_(months) {
  return (
    htmlSectionTitle_("直近12か月", formatHoursMins_(monthsTotal_(months))) +
    htmlBarChart_(
      months.map((m) => m.minutes),
      months.map((m) => m.month + "月"),
      { height: 70, gap: 2, labelSize: 10 }
    )
  );
}

function monthsTotal_(months) {
  return months.reduce((sum, m) => sum + m.minutes, 0);
}

// 棒グラフ（画像を使わず、高さを指定したセルで描く。Gmail などでも崩れない）
// options: height（棒の最大の高さ）・gap（棒の間の余白）・labelSize（下の文字の大きさ）・valueLabel（棒の上の文字）
function htmlBarChart_(values, labels, options) {
  const c = MAIL_COLORS;
  const maxHeight = options.height;
  const gap = options.gap === undefined ? 4 : options.gap;
  const labelSize = options.labelSize || 12;
  const max = Math.max.apply(null, values);
  const width = (100 / values.length).toFixed(2) + "%";
  const bars = values
    .map((mins) => {
      const height = mins > 0 ? Math.max(3, Math.round((mins / max) * maxHeight)) : 2;
      const valueHtml = options.valueLabel
        ? '<div style="font-size:11px;color:' + c.muted + ';white-space:nowrap;">' + options.valueLabel(mins) + "</div>"
        : "";
      return (
        '<td valign="bottom" align="center" style="width:' + width + ";padding:0 " + gap + 'px;">' +
        valueHtml +
        '<div style="height:' + height + "px;margin-top:4px;border-radius:" + (gap > 1 ? "4px 4px" : "2px 2px") +
        " 0 0;background:" + (mins > 0 ? c.accent : c.border) + ';line-height:1px;font-size:1px;">&nbsp;</div>' +
        "</td>"
      );
    })
    .join("");
  const labelCells = labels
    .map(
      (label) =>
        '<td align="center" style="padding-top:6px;font-size:' + labelSize + "px;color:" + c.muted +
        ';white-space:nowrap;">' + label + "</td>"
    )
    .join("");

  return (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="height:' +
    (maxHeight + (options.valueLabel ? 24 : 8)) + 'px;">' +
    "<tr>" + bars + "</tr>" +
    '<tr><td colspan="' + values.length + '" style="border-top:1px solid ' + c.border +
    ';font-size:1px;line-height:1px;">&nbsp;</td></tr>' +
    "<tr>" + labelCells + "</tr></table>"
  );
}

// 作業内容ごとの割合バー（上位5件、残りは「その他」）
function htmlTaskBars_(current) {
  const c = MAIL_COLORS;
  const entries = Object.keys(current.taskMap)
    .map((task) => [task, current.taskMap[task]])
    .sort((a, b) => b[1] - a[1]);
  const top = entries.slice(0, 5);
  const rest = entries.slice(5).reduce((sum, entry) => sum + entry[1], 0);
  if (rest > 0) top.push(["その他", rest]);

  const rows = top
    .map(([task, mins]) => {
      const pct = Math.round((mins / current.totalMinutes) * 100);
      return (
        '<tr><td style="padding:10px 0 0;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>' +
        '<td style="font-size:14px;">' + escapeHtml_(task) + "</td>" +
        '<td align="right" style="font-size:13px;color:' + c.muted + ';white-space:nowrap;">' +
        formatHoursMins_(mins) + "（" + pct + "%）</td></tr></table>" +
        '<div style="margin-top:5px;height:8px;border-radius:4px;background:' + c.paper + ';">' +
        '<div style="width:' + Math.max(pct, 2) + "%;height:8px;border-radius:4px;background:" + c.accent + ';"></div>' +
        "</div></td></tr>"
      );
    })
    .join("");

  return (
    htmlSectionTitle_("作業内容別") +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + rows + "</table>"
  );
}

// 見出し。note を渡すと、右側に小さく添える（「直近30日　12時間30分」など）
function htmlSectionTitle_(title, note) {
  const noteHtml = note
    ? '<span style="margin-left:8px;font-size:13px;font-weight:normal;color:' + MAIL_COLORS.muted + ';">' + note + "</span>"
    : "";
  return '<div style="margin:28px 0 12px;font-size:14px;font-weight:bold;">' + title + noteHtml + "</div>";
}

function escapeHtml_(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
