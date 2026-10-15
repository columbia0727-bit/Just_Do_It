// 週次レポート配信サービス（gas/report_service/*.js）のテスト
// GasTest.createEnv で本物のコードを模擬環境に読み込み、アプリと同じ形でリクエストを送って確かめる
(function (global) {
  const tests = [];
  const test = (name, fn) => tests.push({ name, fn });

  function assertEqual(actual, expected, message) {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a !== e) throw new Error(`${message || "値が違います"}\n  実際: ${a}\n  期待: ${e}`);
  }
  const assertTrue = (value, message) => assertEqual(Boolean(value), true, message);
  const id = (ch) => ch.repeat(32);
  const at = (y, m, d, h, min = 0) => new Date(y, m - 1, d, h, min);

  // ==========================================
  // 登録
  // ==========================================
  test("確認コードは6桁で、毎回変わる", (code) => {
    const gas = global.GasTest.createEnv(code);
    const codes = new Set();
    for (let i = 0; i < 30; i++) {
      gas.post({ action: "register", email: `user${i}@example.com` });
      if (i === 14) gas.setNow(at(2026, 10, 14, 13)); // 1時間あたりの上限に当たらないよう、途中で時計を進める
      const pending = gas.cache[`code:user${i}@example.com`];
      const value = JSON.parse(pending.value).code;
      assertTrue(/^\d{6}$/.test(value), `6桁の数字ではない: ${value}`);
      codes.add(value);
    }
    assertTrue(codes.size >= 28, `確認コードが偏っている（30回中 ${codes.size} 種類）`);
  });

  test("正しい確認コードでトークンが発行され、間違えると入力し直せる", (code) => {
    const gas = global.GasTest.createEnv(code);
    gas.post({ action: "register", email: "me@example.com" });
    const right = JSON.parse(gas.cache["code:me@example.com"].value).code;
    const wrong = right === "000000" ? "111111" : "000000";
    assertEqual(gas.post({ action: "verify", email: "me@example.com", code: wrong }).code, "invalid_code");
    const result = gas.post({ action: "verify", email: "me@example.com", code: right });
    assertEqual(result.status, "success");
    assertTrue(/^[0-9a-f]{64}$/.test(result.token), "トークンの形式が違う");
    assertEqual(gas.rows("tokens")[0][0].length, 64, "トークンはハッシュで保存する");
    assertTrue(gas.rows("tokens")[0][0] !== result.token, "トークンをそのまま保存している");
  });

  test("確認コードの送信は、同じアドレスへ1分に1回・サービス全体で1時間に15通まで", (code) => {
    const gas = global.GasTest.createEnv(code);
    assertEqual(gas.post({ action: "register", email: "me@example.com" }).status, "success");
    assertEqual(gas.post({ action: "register", email: "me@example.com" }).code, "rate_limited");

    const results = [];
    for (let i = 0; i < 16; i++) results.push(gas.post({ action: "register", email: `other${i}@example.com` }).status);
    assertEqual(results.filter((s) => s === "success").length, 14, "1時間に15通（最初の1通を含む）を超えて送っている");
    gas.setNow(at(2026, 10, 14, 13, 5));
    assertEqual(gas.post({ action: "register", email: "next@example.com" }).status, "success", "次の1時間には送れる");
  });

  test("メールアドレスの変更は、新しいアドレスの確認コードで行い、記録・ほかの PC はそのまま", (code) => {
    const gas = global.GasTest.createEnv(code);
    const pc1 = gas.signUp("old@example.com");
    const pc2 = gas.signUp("old@example.com");
    gas.post({ action: "log", token: pc1, datetime: "2026-10-13 09:00:00", task: "制作", minutes: 25, id: id("a") });

    gas.post({ action: "register", email: "New@Example.com" });
    const right = JSON.parse(gas.cache["code:new@example.com"].value).code;
    const wrong = right === "000000" ? "111111" : "000000";
    assertEqual(gas.post({ action: "change_email", token: pc1, email: "new@example.com", code: wrong }).code, "invalid_code");
    assertEqual(gas.post({ action: "change_email", token: "nope", email: "new@example.com", code: right }).code, "unauthorized");
    assertEqual(
      gas.post({ action: "change_email", token: pc1, email: "New@Example.com", code: right }),
      { status: "success", email: "new@example.com" }
    );
    assertEqual(gas.rows("users").map((row) => [row[1], row[2]]), [["new@example.com", "active"]]);
    const pulled = gas.post({ action: "sync_pull", token: pc2 });
    assertEqual([pulled.email, pulled.logs.length], ["new@example.com", 1], "ほかの PC に新しいアドレス・記録が見えない");
    gas.post({ action: "send_test_report", token: pc2 });
    assertEqual(gas.mails[gas.mails.length - 1].to, "new@example.com", "レポートが新しいアドレスに届かない");
  });

  test("ほかの人が使っているアドレスには変えられず、配信を停止した以前の登録のアドレスには変えられる", (code) => {
    const gas = global.GasTest.createEnv(code);
    const me = gas.signUp("me@example.com");
    gas.signUp("other@example.com");
    gas.post({ action: "unregister", token: gas.signUp("old@example.com") });

    delete gas.cache["resend:other@example.com"]; // 登録したときの「1分に1回」の制限を外す
    gas.post({ action: "register", email: "other@example.com" });
    const otherCode = JSON.parse(gas.cache["code:other@example.com"].value).code;
    assertEqual(gas.post({ action: "change_email", token: me, email: "other@example.com", code: otherCode }).code, "email_in_use");
    assertTrue(gas.cache["code:other@example.com"], "使えないアドレスなのに、確認コードを使い切った");

    delete gas.cache["resend:old@example.com"];
    gas.post({ action: "register", email: "old@example.com" });
    const oldCode = JSON.parse(gas.cache["code:old@example.com"].value).code;
    assertEqual(gas.post({ action: "change_email", token: me, email: "old@example.com", code: oldCode }).status, "success");
    assertEqual(
      gas.rows("users").map((row) => [row[1], row[2]]),
      [["old@example.com", "active"], ["other@example.com", "active"]],
      "配信を停止した以前の登録が残っている"
    );
  });

  // ==========================================
  // 記録の追加・修正・削除
  // ==========================================
  test("同じ ID の記録は二重に保存しない。正しくない記録やトークンは受け付けない", (code) => {
    const gas = global.GasTest.createEnv(code);
    const token = gas.signUp("me@example.com");
    const log = { action: "log", token, datetime: "2026-10-13 09:00:00", task: "制作", minutes: 25, id: id("a") };
    gas.post(log);
    gas.post(log); // 通信の行き違いで再送された
    assertEqual(gas.rows("logs").length, 1);
    assertEqual(gas.post({ ...log, minutes: 0, id: id("b") }).code, "invalid");
    assertEqual(gas.post({ ...log, datetime: "昨日", id: id("b") }).code, "invalid");
    assertEqual(gas.post({ ...log, token: "nope", id: id("b") }).code, "unauthorized");
  });

  test("記録の修正・削除は、ID か（ID のない古い記録は）内容で探し、消した ID を残す", (code) => {
    const gas = global.GasTest.createEnv(code);
    const token = gas.signUp("me@example.com");
    const other = gas.signUp("other@example.com");
    gas.post({ action: "log", token, datetime: "2026-10-12 09:00:00", task: "制作", minutes: 25, id: id("a") });
    gas.post({ action: "log", token, datetime: "2026-10-13 09:00:00", task: "読書", minutes: 20 }); // ID のない古い記録
    gas.post({ action: "log", token, datetime: "2026-10-13 10:00:00", task: "=SUM(1)", minutes: 5, id: id("b") });
    gas.post({ action: "log", token: other, datetime: "2026-10-13 09:00:00", task: "読書", minutes: 20, id: id("c") });

    gas.post({ action: "update_log", token, id: id("a"), datetime: "2026-10-12 09:00:00", task: "制作", minutes: 25, new_task: "ポートフォリオ制作", new_minutes: 30, new_id: id("d") });
    gas.post({ action: "update_log", token, id: id("e"), datetime: "2026-10-13 09:00:00", task: "読書", minutes: 20, new_task: "読書（技術書）", new_minutes: 40, new_id: id("f") });
    gas.post({ action: "delete_log", token, id: id("b"), datetime: "2026-10-13 10:00:00", task: "=SUM(1)", minutes: 5 });
    const notFound = gas.post({ action: "delete_log", token, id: id("9"), datetime: "2026-01-01 09:00:00", task: "古い", minutes: 5 });

    assertEqual(
      gas.rows("logs").map((row) => [row[2], row[3]]),
      [["ポートフォリオ制作", "30"], ["読書（技術書）", "40"], ["読書", "20"]],
      "直した内容・消した記録・ほかの人の記録が正しくない"
    );
    assertEqual(notFound, { status: "success", deleted: false }, "見つからない記録は、何もしないで成功とする");
    assertEqual(gas.rows("deleted").map((row) => row[1][0]), ["a", "e", "b", "9"], "消した（直す前の）ID が残っていない");
  });

  test("記録の修正で、日時も直せる（new_datetime を省略すると日時はそのまま）", (code) => {
    const gas = global.GasTest.createEnv(code);
    const token = gas.signUp("me@example.com");
    gas.post({ action: "log", token, datetime: "2026-10-14 09:00:00", task: "制作", minutes: 25, id: id("a") });
    gas.post({ action: "update_log", token, id: id("a"), datetime: "2026-10-14 09:00:00", task: "制作", minutes: 25,
      new_datetime: "2026-10-13 21:30:00", new_task: "制作", new_minutes: 25, new_id: id("b") });
    assertEqual(gas.rows("logs").map((row) => [row[1], row[4]]), [["2026-10-13 21:30:00", id("b")]]);
    assertEqual(gas.post({ action: "update_log", token, id: id("b"), datetime: "2026-10-13 21:30:00", task: "制作",
      minutes: 25, new_datetime: "あした", new_task: "制作", new_minutes: 25, new_id: id("c") }).code, "invalid");
  });

  // ==========================================
  // 同期
  // ==========================================
  test("sync_pull は自分の記録と消した ID・届くタイミングを返し、ID はアプリと同じ計算で作る", (code) => {
    const gas = global.GasTest.createEnv(code);
    const pc1 = gas.signUp("me@example.com", { weekday: 0, hour: 9 });
    const pc2 = gas.signUp("me@example.com", { weekday: 6, hour: 21 }); // あとから登録した PC のタイミングが優先
    const other = gas.signUp("other@example.com");
    gas.post({ action: "log", token: pc1, datetime: "2026-10-13 09:00:00", task: "読書", minutes: 20 }); // ID なし
    gas.post({ action: "log", token: pc1, datetime: "2026-10-13 10:00:00", task: "=SUM(1)", minutes: 5, id: id("b") });
    gas.post({ action: "log", token: other, datetime: "2026-10-13 09:00:00", task: "ほかの人", minutes: 30, id: id("c") });

    const pulled = gas.post({ action: "sync_pull", token: pc2 });
    assertEqual(
      pulled.logs.map((log) => [log.datetime, log.task, log.minutes, log.id]),
      [
        // アプリ（Python）の report_service.log_id と同じ値（tests/test_report_service.py でも同じ値を確かめている）
        ["2026-10-13 09:00:00", "読書", 20, "d6ca0a222ae131bf471bfa88fff6a945"],
        ["2026-10-13 10:00:00", "=SUM(1)", 5, id("b")], // 数式よけの「'」を外して、入力したとおりに戻す
      ]
    );
    assertEqual([pulled.weekday, pulled.hour, pulled.retention_days], [6, 21, 400]);
    assertEqual(pulled.deleted, []);
  });

  // ==========================================
  // 週次レポート
  // ==========================================
  function runHourly(gas, from, to) {
    for (let t = from.getTime(); t < to.getTime(); t += 3600 * 1000) {
      gas.setNow(new Date(t + 5 * 60 * 1000));
      gas.api.sendDueReports();
    }
  }

  test("選んだ曜日・時刻に届き、集計期間は朝なら前日まで・夜ならその日まで", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 10, 30)); // 水曜
    const monday = gas.signUp("monday@example.com", { weekday: 0, hour: 9 });
    const sunday = gas.signUp("sunday@example.com", { weekday: 6, hour: 21 });
    gas.post({ action: "log", token: sunday, datetime: "2026-10-18 09:00:00", task: "日曜の記録", minutes: 30, id: id("a") });
    gas.post({ action: "log", token: monday, datetime: "2026-10-18 09:00:00", task: "日曜の記録", minutes: 30, id: id("b") });
    const before = gas.mails.length;
    runHourly(gas, at(2026, 10, 14, 11), at(2026, 10, 20, 0));

    const reports = gas.mails.slice(before).map((m) => [m.to, m.sentAt.getDay(), m.sentAt.getHours(), m.subject]);
    assertEqual(reports, [
      ["sunday@example.com", 0, 21, "【Just do it.】1週間の作業レポート（10/12〜10/18）"],
      ["monday@example.com", 1, 9, "【Just do it.】1週間の作業レポート（10/12〜10/18）"],
    ]);
  });

  test("レポートに直近30日・直近12か月のグラフと合計が入る（アプリの振り返りの「月」「年」と同じ期間）", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 10, 30));
    const token = gas.signUp("me@example.com", { weekday: 6, hour: 21 }); // 日曜 21時（その日の記録まで集計）
    const log = (datetime, minutes, ch) =>
      gas.post({ action: "log", token, datetime, task: "制作", minutes, id: id(ch) });
    log("2026-10-18 09:00:00", 60, "a"); // この1週間（10/12〜10/18）
    log("2026-09-19 09:00:00", 30, "b"); // 直近30日の最初の日
    log("2026-09-18 09:00:00", 5, "c"); // 30日より前（12か月には入る）
    log("2025-11-01 09:00:00", 120, "d"); // 12か月の最初の月（2025年11月）
    log("2025-10-31 09:00:00", 45, "e"); // 12か月より前
    runHourly(gas, at(2026, 10, 14, 11), at(2026, 10, 18, 22)); // 毎週の定期レポート
    const scheduled = gas.mails.find((m) => m.subject.includes("レポート"));
    gas.setNow(at(2026, 10, 18, 21, 30));
    gas.post({ action: "send_test_report", token }); // テストメール（同じ期間になる）
    const tested = gas.mails[gas.mails.length - 1];
    assertTrue(tested.subject.startsWith("【テスト】"), "テストメールが届いていない");
    assertEqual(scheduled.htmlBody, tested.htmlBody, "定期レポートとテストメールで内容が違う");

    const mail = scheduled;
    assertTrue(mail.body.includes("- 直近30日 : 1時間 30分"), "テキスト版の直近30日が違う\n" + mail.body);
    assertTrue(mail.body.includes("- 直近12か月 : 3時間 35分"), "テキスト版の直近12か月が違う\n" + mail.body);
    assertTrue(/直近30日<span[^>]*>1時間 30分</.test(mail.htmlBody), "HTML の直近30日の合計が違う");
    assertTrue(/直近12か月<span[^>]*>3時間 35分</.test(mail.htmlBody), "HTML の直近12か月の合計が違う");
    const yearChart = mail.htmlBody.slice(mail.htmlBody.indexOf("直近12か月"));
    const monthLabels = [...yearChart.matchAll(/>(\d+)月</g)].map((m) => Number(m[1]));
    assertEqual(monthLabels, [11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "12か月の並びが違う");
    const recentChart = mail.htmlBody.slice(mail.htmlBody.indexOf("直近30日"), mail.htmlBody.indexOf("直近12か月"));
    const dayLabels = [...recentChart.matchAll(/>(\d+\/\d+)</g)].map((m) => m[1]);
    assertEqual(dayLabels, ["9/23", "9/28", "10/3", "10/8", "10/13", "10/18"], "直近30日の日付（5日おき・最新の日を含む）が違う");
  });

  test("ひとことは作業時間に合わせて選び、メールの最初に入る", (code) => {
    const gas = global.GasTest.createEnv(code);
    const week = (totalMinutes, days) => ({ totalMinutes, days });
    const cases = [
      [week(0, 0), week(0, 0), "zeroAgain"],
      [week(0, 0), week(30, 1), "zero"],
      [week(70, 7), week(10, 1), "everyDay"], // 7日すべてが、2倍以上より優先
      [week(60, 3), week(30, 2), "doubled"],
      [week(20, 1), week(0, 0), "small"], // 前の週が0分なら「2倍」にはしない
      [week(29, 1), week(20, 1), "small"],
      [week(30, 2), week(20, 1), "warm"],
      [week(119, 2), week(100, 2), "warm"],
      [week(120, 2), week(100, 2), "solid"],
      [week(300, 5), week(200, 5), "intense"],
      [week(120, 7), week(10, 1), "goalReached", 120], // 目標の達成が、7日すべて・2倍以上より優先
      [week(119, 7), week(10, 1), "everyDay", 120], // 目標まであと1分
      [week(0, 0), week(0, 0), "zeroAgain", 0],
    ];
    cases.forEach(([current, previous, kind, goal]) =>
      assertEqual(gas.api.cheerKind_(current, previous, goal || 0), kind, JSON.stringify([current, previous, goal]))
    );

    // 記録のない人に届くレポートは、2週連続0分のひとことで始まる。同じ週なら何度送っても同じ文
    const token = gas.signUp("me@example.com");
    gas.post({ action: "send_test_report", token });
    gas.setNow(at(2026, 10, 14, 12, 30));
    gas.post({ action: "send_test_report", token });
    const [first, second] = gas.mails.filter((m) => m.subject.startsWith("【テスト】"));
    const message = gas.api.CHEER_MESSAGES.zeroAgain.find((text) => first.body.includes(text));
    assertTrue(message, "2週連続0分のひとことが入っていない\n" + first.body);
    assertTrue(first.body.indexOf(message) < first.body.indexOf("[この1週間のサマリー]"), "ひとことがテキスト版の最初にない");
    const htmlAt = first.htmlBody.indexOf(message);
    assertTrue(htmlAt >= 0 && htmlAt < first.htmlBody.indexOf("この1週間の作業時間"), "ひとことが HTML の最初にない");
    assertTrue(second.body.includes(message), "同じ週なのに、ひとことが変わった");
  });

  test("週の目標は登録・変更・同期でき、目標なしの PC をあとから登録しても消えない", (code) => {
    const gas = global.GasTest.createEnv(code);
    const pc1 = gas.signUp("me@example.com", { goal_minutes: 180 });
    assertEqual(gas.post({ action: "sync_pull", token: pc1 }).goal_minutes, 180);
    const pc2 = gas.signUp("me@example.com", { goal_minutes: 0 }); // 目標を決めていない PC
    assertEqual(gas.post({ action: "sync_pull", token: pc2 }).goal_minutes, 180, "ほかの PC で決めた目標が消えた");

    assertEqual(gas.post({ action: "update_goal", token: pc2, goal_minutes: 300 }), { status: "success", goal_minutes: 300 });
    assertEqual(gas.post({ action: "sync_pull", token: pc1 }).goal_minutes, 300);
    assertEqual(gas.post({ action: "update_goal", token: pc1, goal_minutes: 0 }).goal_minutes, 0, "目標なしに戻せない");
    for (const bad of [-1, 1.5, "3時間", 100 * 60 + 1]) {
      assertEqual(gas.post({ action: "update_goal", token: pc1, goal_minutes: bad }).code, "invalid", String(bad));
    }
    assertEqual(gas.post({ action: "update_goal", token: "nope", goal_minutes: 60 }).code, "unauthorized");
    // 目標の列が無い古いシートの利用者も、目標なしとして読める
    const other = gas.signUp("other@example.com");
    assertEqual(gas.post({ action: "sync_pull", token: other }).goal_minutes, 0);
  });

  test("週の目標を決めていると、レポートに達成・あと何分かが入り、達成した週は専用のひとことになる", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 10, 30));
    const token = gas.signUp("me@example.com", { weekday: 6, hour: 21, goal_minutes: 120 });
    gas.post({ action: "log", token, datetime: "2026-10-17 09:00:00", task: "制作", minutes: 90, id: id("a") });
    runHourly(gas, at(2026, 10, 14, 11), at(2026, 10, 18, 22)); // 毎週の定期レポート（日曜 21時）
    let mail = gas.mails.find((m) => m.subject.includes("レポート"));
    assertTrue(mail.body.includes("- 週の目標 : 目標 2時間 ・ あと 30分"), "テキスト版\n" + mail.body);
    assertTrue(mail.htmlBody.includes("目標 2時間 ・ あと 30分"), "HTML 版");

    gas.post({ action: "log", token, datetime: "2026-10-18 09:00:00", task: "制作", minutes: 40, id: id("b") });
    gas.setNow(at(2026, 10, 18, 21, 45));
    gas.post({ action: "send_test_report", token });
    mail = gas.mails[gas.mails.length - 1];
    assertTrue(mail.body.includes("- 週の目標 : 目標 2時間 ・ 達成！"), "テキスト版\n" + mail.body);
    assertTrue(gas.api.CHEER_MESSAGES.goalReached.some((text) => mail.body.includes(text)), "達成のひとことではない");

    // 目標なしなら、目標の行は出さない
    gas.post({ action: "update_goal", token, goal_minutes: 0 });
    gas.setNow(at(2026, 10, 18, 22, 0));
    gas.post({ action: "send_test_report", token });
    assertTrue(!gas.mails[gas.mails.length - 1].body.includes("週の目標"), "目標なしなのに目標の行がある");
  });

  test("届くタイミングを変えた直後に、同じ週のレポートが2通届かない", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 10, 30));
    const token = gas.signUp("me@example.com", { weekday: 6, hour: 21 });
    runHourly(gas, at(2026, 10, 14, 11), at(2026, 10, 18, 22)); // 日曜 21時に届く
    gas.setNow(at(2026, 10, 18, 22, 30));
    gas.post({ action: "update_schedule", token, weekday: 0, hour: 9 }); // 翌日の月曜 9時に変えた
    runHourly(gas, at(2026, 10, 18, 23), at(2026, 10, 27, 0));
    assertEqual(gas.mails.filter((m) => m.subject.includes("レポート")).map((m) => `${m.sentAt.getMonth() + 1}/${m.sentAt.getDate()}`), ["10/18", "10/26"]);
  });

  test("テストメールは10分に1回・1日3回まで", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 14, 0));
    const token = gas.signUp("me@example.com");
    const results = [];
    for (const [h, m] of [[14, 0], [14, 5], [14, 15], [14, 30], [14, 45]]) {
      gas.setNow(at(2026, 10, 14, h, m));
      results.push(gas.post({ action: "send_test_report", token }).status);
    }
    gas.setNow(at(2026, 10, 15, 9, 0));
    results.push(gas.post({ action: "send_test_report", token }).status);
    assertEqual(results, ["success", "error", "success", "success", "error", "success"]);
    assertTrue(gas.mails.filter((m) => m.subject.startsWith("【テスト】")).length === 4, "件名に【テスト】が付いていない");
  });

  // ==========================================
  // 登録の解除・配信停止・古い記録の削除
  // ==========================================
  test("この PC の登録を解除すると、その PC のトークンだけが消え、ほかの PC と記録は残る", (code) => {
    const gas = global.GasTest.createEnv(code);
    const pc1 = gas.signUp("me@example.com");
    const pc2 = gas.signUp("me@example.com");
    gas.post({ action: "log", token: pc1, datetime: "2026-10-13 09:00:00", task: "制作", minutes: 25, id: id("a") });
    assertEqual(gas.post({ action: "remove_device", token: pc1 }).status, "success");
    assertEqual(gas.post({ action: "sync_pull", token: pc1 }).code, "unauthorized", "解除した PC のトークンが使える");
    assertEqual(gas.post({ action: "sync_pull", token: pc2 }).logs.length, 1, "ほかの PC から記録が見えない");
    assertEqual(gas.rows("users")[0][2], "active", "メールの配信まで止まっている");
  });

  test("すべての PC で配信を停止すると、トークン・記録・消した ID がすべて消える", (code) => {
    const gas = global.GasTest.createEnv(code);
    const pc1 = gas.signUp("me@example.com");
    const pc2 = gas.signUp("me@example.com");
    const other = gas.signUp("other@example.com");
    gas.post({ action: "log", token: pc1, datetime: "2026-10-13 09:00:00", task: "制作", minutes: 25, id: id("a") });
    gas.post({ action: "delete_log", token: pc1, id: id("a"), datetime: "2026-10-13 09:00:00", task: "制作", minutes: 25 });
    gas.post({ action: "log", token: other, datetime: "2026-10-13 09:00:00", task: "ほかの人", minutes: 30, id: id("c") });
    gas.post({ action: "unregister", token: pc2 });
    assertEqual(gas.post({ action: "sync_pull", token: pc1 }).code, "unauthorized");
    assertEqual(gas.rows("logs").map((row) => row[2]), ["ほかの人"]);
    assertEqual(gas.rows("deleted").length, 0);
    assertEqual(gas.rows("users").map((row) => row[2]), ["unsubscribed", "active"]);
  });

  test("メールの配信停止リンクは、署名が正しいときだけ停止できる", (code) => {
    const gas = global.GasTest.createEnv(code);
    gas.signUp("me@example.com");
    const userId = gas.rows("users")[0][0];
    let rejected = false;
    try { gas.api.confirmUnsubscribe(userId, "wrong"); } catch (e) { rejected = true; }
    assertTrue(rejected, "署名が違うのに停止できた");
    // 正しい署名は、レポートのメールに載る配信停止リンクから取り出す
    gas.post({ action: "send_test_report", token: gas.signUp("me@example.com") });
    const sig = gas.mails[gas.mails.length - 1].body.match(/sig=([0-9a-f]+)/)[1];
    gas.api.confirmUnsubscribe(userId, sig);
    assertEqual(gas.rows("users")[0][2], "unsubscribed");
  });

  test("400日より前の記録と消した ID は、毎日4時台に削除される", (code) => {
    const gas = global.GasTest.createEnv(code, at(2026, 10, 14, 12));
    const token = gas.signUp("me@example.com");
    gas.post({ action: "log", token, datetime: "2026-10-13 09:00:00", task: "古い", minutes: 25, id: id("a") });
    gas.post({ action: "log", token, datetime: "2026-10-14 09:00:00", task: "新しい", minutes: 25, id: id("b") });
    gas.post({ action: "delete_log", token, id: id("a"), datetime: "2026-10-13 09:00:00", task: "古い", minutes: 25 });
    gas.post({ action: "log", token, datetime: "2026-10-13 09:00:00", task: "古い", minutes: 25, id: id("c") });
    gas.setNow(at(2027, 11, 18, 4, 5)); // 2026-10-13 から400日以上あと、2026-10-14 からちょうど400日
    gas.api.sendDueReports();
    assertEqual(gas.rows("logs").map((row) => row[2]), ["新しい"]);
    assertEqual(gas.rows("deleted").length, 1, "消した ID も、記録と同じ日数で削除する（10/14 に消したものは残る）");
  });

  global.GasTest = global.GasTest || {};
  global.GasTest.tests = tests;
})(typeof globalThis !== "undefined" ? globalThis : this);
