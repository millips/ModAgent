const assert = require('node:assert/strict');
const Module = require('node:module');
const previous = Module._load;
const handlers = {};
Module._load = function(request, ...args) {
  if (request === 'electron') return {
    app: { isPackaged: true }, dialog: {},
    ipcMain: { handle: (name, handler) => { handlers[name] = handler; } },
  };
  if (request === 'electron-log') return {};
  if (request === 'electron-updater') throw new Error('isolated candidate attempted to load auto updater');
  return previous.call(this, request, ...args);
};
try {
  const { setupAutoUpdater } = require('../updater');
  const result = setupAutoUpdater({
    identity: { candidateId: 'core-safety-test' },
    diagnostics: { logger: { info() {} } },
  });
  assert.equal(result, null);
  assert.equal(typeof handlers['check-for-app-update'], 'function');
  handlers['check-for-app-update']().then(response => {
    assert.equal(response.disabled, true);
    assert.equal(response.available, false);
    console.log('CANDIDATE UPDATER ISOLATION TEST PASSED');
  });
} finally { Module._load = previous; }
