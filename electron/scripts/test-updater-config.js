const assert = require('assert')
const path = require('path')

// updater.js normally loads inside Electron. Stub the minimum surface needed
// to test the pure configuration gate without starting a desktop process.
const Module = require('module')
const originalLoad = Module._load
Module._load = function load(request, parent, isMain) {
  if (request === 'electron') {
    return { app: {}, dialog: {}, ipcMain: {} }
  }
  if (request === 'electron-log') return {}
  return originalLoad.call(this, request, parent, isMain)
}

let helpers
try {
  helpers = require('../updater')
} finally {
  Module._load = originalLoad
}

const resources = path.join('C:', 'ModAgent', 'resources')
assert.strictEqual(
  helpers.updateConfigurationPath(resources),
  path.join(resources, 'app-update.yml'),
)
assert.strictEqual(helpers.hasUpdateConfiguration(resources, () => true), true)
assert.strictEqual(helpers.hasUpdateConfiguration(resources, () => false), false)

console.log('UPDATER CONFIGURATION TESTS PASSED')
