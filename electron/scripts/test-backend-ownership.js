const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../main.js'), 'utf8');
const start = source.indexOf('function waitForAPI(');
const end = source.indexOf('\nfunction finishSmokeTest', start);
const fn = source.slice(start, end);
async function check(status) {
  const seen = [];
  const context = { API_BASE: 'http://127.0.0.1:54321', API_TOKEN: 'fake-run-token',
    http: { get(url, options, callback) {
      seen.push({ url, options });
      callback({ statusCode: status, resume() {} });
      return { on() {}, setTimeout() {} };
    } }, setTimeout(fn) { fn(); } };
  vm.createContext(context);
  vm.runInContext(fn, context);
  if (status === 200) await context.waitForAPI(1);
  else await assert.rejects(context.waitForAPI(1), /health check failed/);
  assert.equal(seen[0].url, 'http://127.0.0.1:54321/status');
  assert.equal(seen[0].options.headers['X-ModAgent-Token'], 'fake-run-token');
}
(async () => {
  await check(200);
  await check(403);
  assert(source.includes('findAvailableApiPort(TEST_PROFILE || IS_SMOKE_TEST ? 0 : API_PORT)'));
  console.log('Backend ownership: own token required, foreign token refused, isolated candidate port');
})().catch(error => { console.error(error); process.exitCode = 1; });
