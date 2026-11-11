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
assert(helpers.compareVersions('1.3.1', '1.3.0') > 0)
assert(helpers.compareVersions('1.3.0', '1.3.0') === 0)
assert(helpers.compareVersions('1.2.9', '1.3.0') < 0)
const ordered=['1.7.0-alpha','1.7.0-alpha.1','1.7.0-alpha.beta','1.7.0-beta','1.7.0-beta.2','1.7.0-beta.10','1.7.0-rc.1','1.7.0']
for(let i=0;i<ordered.length;i++)for(let j=0;j<ordered.length;j++){
  assert.equal(Math.sign(helpers.compareVersions(ordered[i],ordered[j])),Math.sign(i-j))
}
assert.equal(helpers.compareVersions('1.7.0+build.2','1.7.0+build.10'),0)
for(const invalid of ['1.7','1.7.0-beta.01','01.7.0','1.7.0-','oops'])assert.throws(()=>helpers.compareVersions(invalid,'1.7.0'),/UPDATE_INVALID_VERSION/)

console.log('UPDATER CONFIGURATION TESTS PASSED')
