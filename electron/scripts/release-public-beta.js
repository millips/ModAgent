const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')
const { getAppIdentity } = require('../appIdentity')
const packageInfo = require('../package.json')

const electronRoot = path.resolve(__dirname, '..')
const env = {
  ...process.env,
  MODAGENT_EDITION: 'subscription',
  MODAGENT_CHANNEL: 'beta',
}
process.env.MODAGENT_EDITION = 'subscription'
process.env.MODAGENT_CHANNEL = 'beta'
const identity = getAppIdentity({
  ...packageInfo,
  modagentEdition: 'subscription',
  modagentChannel: 'beta',
})

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: electronRoot,
    env,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  })
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with ${result.status}`)
  }
}

function output(command, args) {
  const result = spawnSync(command, args, {
    cwd: path.resolve(electronRoot, '..'),
    encoding: 'utf8',
  })
  return result.status === 0 ? result.stdout.trim() : ''
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

run('npm.cmd', ['run', 'test:uninstaller'])
run('npm.cmd', ['run', 'build:backend'])
run('npm.cmd', ['run', 'build'])
run('npx.cmd', [
  'electron-builder', '--win', 'nsis', '--config', 'electron-builder.config.cjs',
])

const outputDir = path.join(electronRoot, 'release', identity.updateChannel)
const executable = path.join(
  outputDir, 'win-unpacked', `${identity.executableName}.exe`,
)
const installer = path.join(
  outputDir, `${identity.artifactPrefix}-Setup-${packageInfo.version}.exe`,
)
for (const required of [executable, installer]) {
  if (!fs.existsSync(required)) throw new Error(`Beta artifact missing: ${required}`)
}

run('node', [
  'scripts/test-packaged-smoke.js',
  '--exe', executable,
  '--edition', identity.edition,
])

const manifest = {
  schema: 1,
  edition: identity.edition,
  channel: identity.channel,
  updateChannel: identity.updateChannel,
  version: packageInfo.version,
  commit: output('git', ['rev-parse', 'HEAD']),
  builtAt: new Date().toISOString(),
  installer: path.basename(installer),
  installerSha256: sha256(installer),
  executableSha256: sha256(executable),
}
fs.writeFileSync(
  path.join(outputDir, 'public-beta-manifest.json'),
  JSON.stringify(manifest, null, 2),
)
console.log(`Public beta ready: ${outputDir}`)
