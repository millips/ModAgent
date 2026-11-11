const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
if (!process.versions.electron) {
  const result = require('node:child_process').spawnSync(require('electron'), [__filename], {
    encoding: 'utf8', timeout: 30000, windowsHide: true,
  });
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
} else {
  const { app, BrowserWindow, ipcMain } = require('electron');
  const { registerShareFileIpc } = require('../shareFile');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-share-ipc-'));
  app.setPath('userData', path.join(root, 'profile'));
  app.disableHardwareAcceleration();
  let owner, other, cancelled = false, dialogs = 0;
  const output = path.join(root, 'saved.json');
  registerShareFileIpc({ ipcMain, getWindow: () => owner, dialog: { showSaveDialog: async (window, options) => {
    assert.equal(window, owner);
    assert.equal(options.filters[0].extensions[0], 'json');
    dialogs++;
    return cancelled ? { canceled: true } : { filePath: output };
  } } });
  app.whenReady().then(async () => {
    const options = { show: false, webPreferences: { preload: path.resolve(__dirname, '../preload.js'), sandbox: true, contextIsolation: true, nodeIntegration: false } };
    owner = new BrowserWindow(options);
    other = new BrowserWindow(options);
    const page = path.join(root, 'fixture.html');
    fs.writeFileSync(page, '<html><body>Share IPC fixture</body></html>');
    await owner.loadFile(page);
    await other.loadFile(page);
    const payload = { text: JSON.stringify({ mods: [{ name: 'IPC 中文' }] }), filename: 'fixture.json' };
    const call = `window.modagent.saveShareFile(${JSON.stringify(payload)})`;
    assert.deepEqual(await owner.webContents.executeJavaScript(call), { ok: true, filename: 'saved.json' });
    assert.equal(fs.readFileSync(output, 'utf8'), payload.text);
    assert.equal((await other.webContents.executeJavaScript(call)).error, 'SHARE_SAVE_UNTRUSTED');
    assert.equal(dialogs, 1, 'untrusted window must not even open a save dialog');
    cancelled = true;
    assert.equal((await owner.webContents.executeJavaScript(call)).cancelled, true);
    assert.equal(fs.readFileSync(output, 'utf8'), payload.text);
    console.log('SHARE IPC PASSED: real sandboxed preload -> IPC -> file write/readback; other window rejected; cancellation preserved file. Native dialog selection simulated.');
    owner.destroy(); other.destroy();
    app.exit(0);
  }).catch(error => { console.error(error); owner?.destroy(); other?.destroy(); app.exit(1); });
  // Profile removal is deliberately omitted: Electron may still hold its files.
}
