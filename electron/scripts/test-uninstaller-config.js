const assert = require('assert')
const fs = require('fs')
const path = require('path')

const electronRoot = path.resolve(__dirname, '..')
const config = require('../electron-builder.config.cjs')

assert.strictEqual(
  config.nsis.deleteAppDataOnUninstall,
  false,
  'User data deletion must remain an explicit uninstall choice',
)

for (const relative of ['build/installer.nsh', 'build/installer-beta.nsh']) {
  const source = fs.readFileSync(path.join(electronRoot, relative), 'utf8')
  const killIndex = source.indexOf('/IM ModAgentBackend.exe')
  const cleanupIndex = source.indexOf('${ifNot} ${isUpdated}')

  assert(killIndex >= 0, `${relative} must terminate the packaged backend`)
  assert(
    cleanupIndex > killIndex,
    `${relative} must stop the backend for both updates and full uninstalls`,
  )
  assert(source.includes('Sleep 800'), `${relative} must wait for file handles to close`)
  assert(source.includes('/SD IDYES'), `${relative} must have a safe silent-mode default`)
  assert(!/steamapps|\\Mods\\|BepInEx/i.test(source), `${relative} must never remove game Mod directories`)
}

const beta = fs.readFileSync(path.join(electronRoot, 'build/installer-beta.nsh'), 'utf8')
assert(beta.includes('$PROFILE\\.modagent-beta'))
assert(beta.includes('$LOCALAPPDATA\\ModAgent Pro Beta'))

const stable = fs.readFileSync(path.join(electronRoot, 'build/installer.nsh'), 'utf8')
assert(stable.includes('$PROFILE\\.modagent'))
assert(stable.includes('IDYES uninstall_keep_all'))

console.log('UNINSTALLER CONFIGURATION TESTS PASSED')
