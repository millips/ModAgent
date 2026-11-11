const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createShareFileSaver } = require('../shareFile');

(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'modagent-share-save-'));
  const filePath = path.join(root, 'chosen.json');
  const payload = { filename: '../bad/path.json', text: JSON.stringify({ mods: [{ name: '中文 fixture' }] }) };
  try {
    const save = createShareFileSaver({ choosePath: async filename => {
      assert(!/[\\/]/.test(filename));
      return { filePath };
    } });
    assert.deepEqual(await save(payload), { ok: true, filename: 'chosen.json' });
    assert.equal(await fs.readFile(filePath, 'utf8'), payload.text);
    const cancel = createShareFileSaver({ choosePath: async () => ({ canceled: true }) });
    assert.equal((await cancel(payload)).cancelled, true);
    const fail = createShareFileSaver({ choosePath: async () => ({ filePath }), io: {
      ...fs, rename: async () => { throw Error('fixture locked destination'); },
    } });
    assert.equal((await fail({ ...payload, text: '{"mods":[]}' })).error, 'SHARE_SAVE_FAILED');
    assert.equal(await fs.readFile(filePath, 'utf8'), payload.text, 'failed overwrite preserves original');
    assert.deepEqual(await fs.readdir(root), ['chosen.json'], 'no staging debris');
    let release;
    const locked = createShareFileSaver({ choosePath: () => new Promise(resolve => { release = resolve; }) });
    const pending = locked(payload);
    assert.equal((await locked(payload)).error, 'SHARE_SAVE_BUSY');
    release({ canceled: true });
    await pending;
    assert.equal((await save({ ...payload, text: '{}' })).error, 'SHARE_SAVE_INVALID');
    assert.equal((await save({ ...payload, text: 'x'.repeat(5 * 1024 * 1024 + 1) })).error, 'SHARE_SAVE_INVALID');
    const wrongExtension = createShareFileSaver({ choosePath: async () => ({ filePath: path.join(root, 'unsafe.exe') }) });
    assert.equal((await wrongExtension(payload)).error, 'SHARE_SAVE_JSON_REQUIRED');
    console.log('SHARE FILE PASSED: real UTF-8 readback, safe suggested filename, cancellation, failed overwrite preservation, cleanup, duplicate guard, invalid/oversized JSON and extension rejection');
  } finally {
    // Only the unique test-owned temporary directory is removed.
    await fs.rm(root, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
