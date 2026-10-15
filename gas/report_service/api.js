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
    change_email: handleChangeEmail_,
    log: handleLog_,
    update_log: handleUpdateLog_,
    delete_log: handleDeleteLog_,
    update_schedule: handleUpdateSchedule_,
    send_test_report: handleSendTestReport_,
    sync_pull: handleSyncPull_,
    remove_device: handleRemoveDevice_,
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
