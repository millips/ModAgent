const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const packageInfo = require('../package.json')

function option(name, fallback = '') {
  const index = process.argv.indexOf(name)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const edition = option('--edition', 'subscription')
const defaultExecutable = edition === 'free'
  ? path.resolve(__dirname, '..', 'release', 'free', 'win-unpacked', 'ModAgent.exe')
  : path.resolve(__dirname, '..', 'release', 'subscription', 'win-unpacked', 'ModAgentPro.exe')
const executable = path.resolve(option('--exe', defaultExecutable))

assert(fs.existsSync(executable), `Packaged executable not found: ${executable}`)
assert(['free', 'subscription'].includes(edition), `Unsupported edition: ${edition}`)

const smokeRoot = fs.mkdtempSync(path.join(os.tmpdir(), `modagent-${edition}-smoke-`))
const dataDir = path.join(smokeRoot, 'data')
const userDataDir = path.join(smokeRoot, 'user-data')
fs.mkdirSync(dataDir, { recursive: true })
fs.mkdirSync(userDataDir, { recursive: true })

try {
  const result = spawnSync(executable, ['--smoke-test'], {
    encoding: 'utf8',
    timeout: 90000,
    windowsHide: true,
    env: {
      ...process.env,
      MODAGENT_DATA_DIR: dataDir,
      MODAGENT_USER_DATA_DIR: userDataDir,
    },
  })
  if (result.error) throw result.error
  assert.strictEqual(
    result.status,
    0,
    `Packaged app exited with ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  )

  const statePath = path.join(dataDir, 'editions', edition, 'runtime-state.json')
  assert(fs.existsSync(statePath), `Runtime state missing: ${statePath}`)
  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'))
  assert.strictEqual(state.edition, edition)
  assert.strictEqual(state.pendingVersion, packageInfo.version)
  assert.strictEqual(state.healthy, true, 'Backend and renderer never reached healthy state')
  assert.strictEqual(state.lastExitClean, true, 'Packaged app did not exit cleanly')

  const logPath = path.join(dataDir, 'editions', edition, 'logs', 'desktop.log')
  const log = fs.readFileSync(logPath, 'utf8')
  assert(log.includes('ModAgent API ready'), 'Backend health check was not observed')
  assert(log.includes('Packaged smoke test passed'), 'Smoke-test success marker missing')
  const invalidUtf8Lines = log
    .split(/\r?\n/)
    .filter(line => line.includes('\uFFFD'))
  assert.strictEqual(
    invalidUtf8Lines.length,
    0,
    `Backend log contains invalid UTF-8 replacement characters:\n${invalidUtf8Lines.join('\n')}`,
  )
  console.log(`PACKAGED ${edition.toUpperCase()} SMOKE TEST PASSED (${packageInfo.version})`)
} finally {
  fs.rmSync(smokeRoot, { recursive: true, force: true })
}
