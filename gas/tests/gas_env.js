// GAS の代わりの模擬環境。本物の配信サービスのコード（gas/report_service/*.js をつなげたもの）を読み込み、スプレッドシート・キャッシュ・メール・時計を手元で再現する
// （Node.js とブラウザのどちらでも動くよう、Node.js 専用の機能は使わない）
(function (global) {
  const pad = (n) => String(n).padStart(2, "0");

  function makeSheet() {
    const data = [];
    let maxRows = 1000;
    const isFilled = (row) => row && row.some((v) => v !== "" && v !== undefined);
    const sheet = {
      data,
      getLastRow: () => data.reduce((last, row, i) => (isFilled(row) ? i + 1 : last), 0),
      getLastColumn: () =>
        data.reduce((max, row) => Math.max(max, (row || []).reduce((c, v, i) => (v !== "" && v !== undefined ? i + 1 : c), 0)), 0),
      getMaxRows: () => maxRows,
      insertRowsAfter: (_, n) => { maxRows += n; },
      deleteRow: (r) => { data.splice(r - 1, 1); },
      getRange(r, c, nr = 1, nc = 1) {
        const cells = () => {
          const out = [];
          for (let i = 0; i < nr; i++) {
            const row = data[r - 1 + i] || [];
            const values = [];
            for (let j = 0; j < nc; j++) values.push(row[c - 1 + j] === undefined ? "" : row[c - 1 + j]);
            out.push(values);
          }
          return out;
        };
        const range = {
          setNumberFormat: () => range,
          setValues(values) {
            values.forEach((row, i) => {
              data[r - 1 + i] = data[r - 1 + i] || [];
              row.forEach((v, j) => { data[r - 1 + i][c - 1 + j] = v; });
            });
            return range;
          },
          setValue: (v) => range.setValues([[v]]),
          getValues: cells,
          getValue: () => cells()[0][0],
          clearContent() {
            for (let i = 0; i < nr; i++) {
              data[r - 1 + i] = data[r - 1 + i] || [];
              for (let j = 0; j < nc; j++) data[r - 1 + i][c - 1 + j] = "";
            }
            return range;
          },
          createTextFinder(text) {
            const finder = {
              matchEntireCell: () => finder,
              matchCase: () => finder,
              findAll: () => {
                const found = [];
                cells().forEach((row, i) => row.forEach((v) => { if (String(v) === text) found.push({ getRow: () => r + i }); }));
                return found;
              },
              findNext: () => finder.findAll()[0] || null,
            };
            return finder;
          },
        };
        return range;
      },
    };
    return sheet;
  }

  function createEnv(code, start) {
    const RealDate = Date;
    let now = start || new RealDate(2026, 9, 14, 12, 0);
    class FakeDate extends RealDate {
      constructor(...args) {
        if (args.length === 0) super(now.getTime());
        else super(...args);
      }
      static now() { return now.getTime(); }
    }

    const sheets = {};
    const spreadsheet = {
      getSheetByName: (name) => sheets[name] || null,
      insertSheet: (name) => (sheets[name] = makeSheet()),
    };
    const cache = {};
    const mails = [];
    const quota = { remaining: 100 };
    const formatDate = (d, tz, format) => {
      const parts = { yyyy: d.getFullYear(), MM: pad(d.getMonth() + 1), dd: pad(d.getDate()), HH: pad(d.getHours()) };
      if (format === "M/d") return d.getMonth() + 1 + "/" + d.getDate();
      if (format === "yyyyMMddHH") return `${parts.yyyy}${parts.MM}${parts.dd}${parts.HH}`;
      if (format === "yyyyMMdd") return `${parts.yyyy}${parts.MM}${parts.dd}`;
      return `${parts.yyyy}-${parts.MM}-${parts.dd} ${parts.HH}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    };
    // Java と同じく、-128〜127 のバイトで返す
    const signed = (bytes) => bytes.map((b) => (b > 127 ? b - 256 : b));
    const randomHex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");

    const env = {
      SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet },
      Utilities: {
        formatDate,
        getUuid: () => `${randomHex(8)}-${randomHex(4)}-4${randomHex(3)}-a${randomHex(3)}-${randomHex(12)}`,
        computeDigest: (algorithm, text) => signed(global.GasTest.sha256(text)),
        computeHmacSha256Signature: (value, key) => signed(global.GasTest.sha256(key + "|" + value)),
        DigestAlgorithm: { SHA_256: "SHA_256" },
        Charset: { UTF_8: "UTF_8" },
      },
      MailApp: {
        sendEmail: (mail) => { quota.remaining--; mails.push({ ...mail, sentAt: new RealDate(now.getTime()) }); },
        getRemainingDailyQuota: () => quota.remaining,
      },
      LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
      CacheService: {
        getScriptCache: () => ({
          get: (key) => {
            const entry = cache[key];
            if (!entry) return null;
            if (now.getTime() >= entry.until) { delete cache[key]; return null; }
            return entry.value;
          },
          put: (key, value, seconds) => { cache[key] = { value, until: now.getTime() + (seconds || 600) * 1000 }; },
          remove: (key) => { delete cache[key]; },
        }),
      },
      ScriptApp: { getService: () => ({ getUrl: () => "https://example.com/exec" }), getProjectTriggers: () => [], WeekDay: {} },
      Session: { getScriptTimeZone: () => "Asia/Tokyo" },
      PropertiesService: { getScriptProperties: () => ({ getProperty: () => "secret", setProperty: () => {} }) },
      ContentService: { createTextOutput: (text) => ({ text, setMimeType() { return this; } }), MimeType: { JSON: "JSON" } },
      HtmlService: {},
      console: { log() {}, warn() {}, error() {} },
      Date: FakeDate,
    };
    const exported = ["doPost", "sendDueReports", "confirmUnsubscribe", "sha256Hex_", "cheerKind_", "CHEER_MESSAGES"];
    const api = new Function(...Object.keys(env), `${code}\nreturn { ${exported.join(", ")} };`)(...Object.values(env));

    const gas = {
      api,
      sheets,
      mails,
      cache,
      quota,
      setNow: (date) => { now = date; },
      // アプリと同じ形で doPost を呼び、返ってきた JSON を返す
      post: (payload) => JSON.parse(api.doPost({ postData: { contents: JSON.stringify(payload) } }).text),
      // 確認コードの送信 → 確認まで行い、トークンを返す（同じアドレスでも続けて登録できるよう、再送待ちを消しておく）
      signUp(email, extra = {}) {
        delete cache["resend:" + email];
        const sent = gas.post({ action: "register", email });
        if (sent.status !== "success") throw new Error("register failed: " + sent.message);
        const code = JSON.parse(cache["code:" + email].value).code;
        const result = gas.post({ action: "verify", email, code, ...extra });
        if (result.status !== "success") throw new Error("verify failed: " + result.message);
        return result.token;
      },
      rows: (name) => (sheets[name] ? sheets[name].data.slice(1).filter((row) => row.some((v) => v !== "")) : []),
    };
    return gas;
  }

  global.GasTest = global.GasTest || {};
  global.GasTest.createEnv = createEnv;
})(typeof globalThis !== "undefined" ? globalThis : this);
