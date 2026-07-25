const assert = require('assert')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')

const electronRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(electronRoot, '..')
const packageInfo = require(path.join(electronRoot, 'package.json'))
const source = path.join(repoRoot, 'tools', 'cleanup', 'ModAgentCleanup.nsi')
const outputDir = path.join(electronRoot, 'release', 'tools')
const output = path.join(outputDir, `ModAgent-Cleanup-${packageInfo.version}.exe`)
const encodedSource = path.join(outputDir, 'ModAgentCleanup.utf8bom.nsi')

function findMakeNsis() {
  const explicit = process.env.MAKENSIS_PATH
  if (explicit && fs.existsSync(explicit)) return explicit
  const cache = path.join(
    process.env.LOCALAPPDATA || '',
    'electron-builder', 'Cache', 'nsis-3.0.4.1',
  )
  if (!fs.existsSync(cache)) return ''
  const pending = [cache]
  while (pending.length) {
    const current = pending.pop()
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name)
      if (entry.isDirectory()) pending.push(target)
      else if (entry.name.toLowerCase() === 'makensis.exe') return target
    }
  }
  return ''
}

const makensis = findMakeNsis()
assert(makensis, 'makensis.exe was not found in the electron-builder cache')
fs.mkdirSync(outputDir, { recursive: true })
// NSIS 3.0 detects non-ASCII scripts reliably when a UTF-8 BOM is present.
fs.writeFileSync(
  encodedSource,
  '\uFEFF' + fs.readFileSync(source, 'utf8').replace(/^\uFEFF/, ''),
  'utf8',
)

const result = spawnSync(makensis, [
  '/V2',
  `/DPRODUCT_VERSION=${packageInfo.version}`,
  `/DOUTPUT_FILE=${output}`,
  encodedSource,
], {
  cwd: repoRoot,
  encoding: 'utf8',
  windowsHide: true,
})
if (result.status !== 0) {
  throw new Error(`makensis failed\n${result.stdout}\n${result.stderr}`)
}
try { fs.rmSync(encodedSource, { force: true }) } catch (_) {}
assert(fs.existsSync(output), `Cleanup executable was not created: ${output}`)

const dryRunLog = path.join(os.tmpdir(), 'ModAgent-Cleanup-dry-run.txt')
try { fs.rmSync(dryRunLog, { force: true }) } catch (_) {}
const dryRun = spawnSync(output, ['/S', '/DRYRUN=1'], {
  encoding: 'utf8',
  timeout: 30000,
  windowsHide: true,
})
if (dryRun.error) throw dryRun.error
assert.strictEqual(dryRun.status, 0, `Cleanup dry-run exited with ${dryRun.status}`)
assert(fs.existsSync(dryRunLog), 'Cleanup dry-run did not create its plan')
const plan = fs.readFileSync(dryRunLog, 'utf8')
assert(plan.includes('.modagent-beta'), 'Beta data was not included in the default plan')
assert(!plan.includes(`${path.sep}.modagent\r\n`), 'Stable .modagent must be opt-in')
assert(plan.includes('Programs\\ModAgent Pro Beta'), 'Standard Beta install path missing')

const stableDryRun = spawnSync(output, ['/S', '/DRYRUN=1', '/PURGE_STABLE=1'], {
  encoding: 'utf8',
  timeout: 30000,
  windowsHide: true,
})
if (stableDryRun.error) throw stableDryRun.error
assert.strictEqual(
  stableDryRun.status,
  0,
  `Cleanup stable-data dry-run exited with ${stableDryRun.status}`,
)
const stablePlan = fs.readFileSync(dryRunLog, 'utf8')
assert(
  /DIR\t[^\r\n]+\\\.modagent\r?\n/.test(stablePlan),
  'Stable .modagent must be included after explicit opt-in',
)

const sha256 = crypto.createHash('sha256').update(fs.readFileSync(output)).digest('hex')
const manifest = {
  schema: 1,
  version: packageInfo.version,
  builtAt: new Date().toISOString(),
  executable: path.basename(output),
  sha256,
  dryRunVerified: true,
  stableDataDefault: 'preserve',
  stableDataOptInVerified: true,
}
fs.writeFileSync(
  path.join(outputDir, 'cleanup-manifest.json'),
  JSON.stringify(manifest, null, 2) + '\n',
)
console.log(`Cleanup tool ready: ${output}`)
console.log(`SHA256: ${sha256}`)
