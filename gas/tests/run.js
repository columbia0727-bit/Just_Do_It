// GAS のテストを Node.js で実行する（node gas/tests/run.js）
// テストの本体（sha256.js・gas_env.js・code_tests.js）は、ブラウザでも動くよう Node.js の機能を使わずに書いている
const fs = require("fs");
const path = require("path");
const vm = require("vm");

for (const file of ["sha256.js", "gas_env.js", "code_tests.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(__dirname, file), "utf8"), { filename: file });
}
const code = fs.readFileSync(path.join(__dirname, "..", "report_service", "Code.js"), "utf8");

let failed = 0;
for (const { name, fn } of globalThis.GasTest.tests) {
  try {
    fn(code);
    console.log(`ok   ${name}`);
  } catch (error) {
    failed++;
    console.log(`FAIL ${name}\n${error.stack}`);
  }
}
console.log(`\n${globalThis.GasTest.tests.length - failed} / ${globalThis.GasTest.tests.length} passed`);
process.exit(failed ? 1 : 0);
