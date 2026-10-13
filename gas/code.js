var HEADER = ["日時", "作業内容", "実施時間"];

// 記録用のシート（スプレッドシートの1枚目）を取得する
function getLogSheet() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
}

// PythonからのPOSTデータを受け取る窓口
function doPost(e) {
  var sheet = getLogSheet();
  try {
    var data = JSON.parse(e.postData.contents);
    // 初回はヘッダー行を作成する
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(HEADER);
    }
    sheet.appendRow([data.datetime, data.task, data.duration]);
    return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({"status": "error", "message": error.toString()})).setMimeType(ContentService.MimeType.JSON);
  }
}

// 万が一GETアクセスが来たときのエラー防止用
function doGet(e) {
  return ContentService.createTextOutput("GAS Web App is running successfully!");
}


// ==========================================
// 週1回のGmail自動集計レポート送信機能
// ==========================================
function sendWeeklyReport() {
  var sheet = getLogSheet();
  var rows = sheet.getDataRange().getValues();

  var totalMinutes = 0;
  var recordCount = 0;
  // タスク名ごとの時間集計
  var taskMap = {};

  var now = new Date();
  var oneWeekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var dateVal = new Date(row[0]);
    // ヘッダー行や日時が読めない行はスキップ
    if (isNaN(dateVal.getTime()) || dateVal < oneWeekAgo) {
      continue;
    }

    var taskName = String(row[1]);
    var mins = parseInt(String(row[2]).replace(/[^0-9]/g, ''), 10) || 0;
    totalMinutes += mins;
    recordCount++;

    if (!taskMap[taskName]) {
      taskMap[taskName] = 0;
    }
    taskMap[taskName] += mins;
  }

  function formatHoursMins(totalMins) {
    var h = Math.floor(totalMins / 60);
    var m = totalMins % 60;
    return h + "時間 " + m + "分";
  }

  // 作業時間の多い順に並べる
  var tasks = Object.keys(taskMap).sort(function (a, b) {
    return taskMap[b] - taskMap[a];
  });

  var subject = "【Just do it.】今週の作業集計レポート";
  var body = "お疲れ様です！今週の「Just do it.」活動レポートをお届けします。\n\n";
  body += "----------------------------------------\n\n";
  body += "[今週のサマリー]\n";
  body += "- 総作業時間 : " + formatHoursMins(totalMinutes) + "（合計 " + totalMinutes + "分）\n";
  body += "- 記録回数 : " + recordCount + "回\n\n";

  body += "[作業内容別内訳]\n";
  if (tasks.length === 0) {
    body += "- 今週の記録はありませんでした。\n";
  }
  for (var j = 0; j < tasks.length; j++) {
    var task = tasks[j];
    var taskMins = taskMap[task];
    var percentage = totalMinutes > 0 ? Math.round((taskMins / totalMinutes) * 100) : 0;
    body += "- " + task + " : " + formatHoursMins(taskMins) + "（" + percentage + "%）\n";
  }

  body += "\n今週もしっかり積み上げていますね！来週もこの調子で頑張りましょう。\n\n";
  body += "----------------------------------------\n";
  body += "※このメールはGoogle Apps Scriptから自動送信されています。";

  var recipient = Session.getActiveUser().getEmail();
  GmailApp.sendEmail(recipient, subject, body);

  Logger.log("週次レポートを送信しました: " + recipient);
}

// 週次レポートのトリガー（毎週月曜 9時台）を作成する。エディタから1回だけ実行する
function createWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === "sendWeeklyReport") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger("sendWeeklyReport")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(9)
    .create();
}
