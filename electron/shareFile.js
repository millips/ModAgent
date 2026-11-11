const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

// The renderer supplies content, never a writable path. Only the native dialog
// chooses the destination. Stage next to it so a failed write preserves old data.
function createShareFileSaver({ choosePath, io = fs }) {
  let busy = false;
  return async (payload) => {
    if (busy) return { ok: false, error: 'SHARE_SAVE_BUSY' };
    if (!payload || typeof payload.text !== 'string' || Buffer.byteLength(payload.text) > 5 * 1024 * 1024) {
      return { ok: false, error: 'SHARE_SAVE_INVALID' };
    }
    try {
      if (!Array.isArray(JSON.parse(payload.text)?.mods)) throw Error('invalid');
    } catch (_) { return { ok: false, error: 'SHARE_SAVE_INVALID' }; }
    busy = true;
    let staging;
    try {
      const filename = String(payload.filename || 'modagent-share.json').replace(/[\\/:*?"<>|\x00-\x1f]/g, '-').slice(0, 160);
      const selected = await choosePath(filename.endsWith('.json') ? filename : filename + '.json');
      if (selected.canceled || !selected.filePath) return { ok: false, cancelled: true };
      if (path.extname(selected.filePath).toLowerCase() !== '.json') return { ok: false, error: 'SHARE_SAVE_JSON_REQUIRED' };
      staging = selected.filePath + '.' + crypto.randomUUID() + '.tmp';
      await io.writeFile(staging, payload.text, { encoding: 'utf8', flag: 'wx' });
      if (await io.readFile(staging, 'utf8') !== payload.text) throw Error('verification_failed');
      await io.rename(staging, selected.filePath);
      staging = null;
      return { ok: true, filename: path.basename(selected.filePath) };
    } catch (_) {
      return { ok: false, error: 'SHARE_SAVE_FAILED' };
    } finally {
      if (staging) await io.unlink(staging).catch(() => {});
      busy = false;
    }
  };
}
function registerShareFileIpc({ ipcMain, dialog, getWindow }) {
  const save = createShareFileSaver({ choosePath: defaultPath => dialog.showSaveDialog(getWindow(), {
    defaultPath, filters: [{ name: 'ModAgent JSON', extensions: ['json'] }],
  }) });
  ipcMain.handle('save-share-file', (event, payload) => {
    const window = getWindow();
    if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) {
      return { ok: false, error: 'SHARE_SAVE_UNTRUSTED' };
    }
    return save(payload);
  });
}
module.exports = { createShareFileSaver, registerShareFileIpc };
