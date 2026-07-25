const { spawnSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const asar = require('@electron/asar')
const { expectedAudioCount } = require('./verify-commercial-audio')

const electronRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(electronRoot, '..')
const releaseRoot = path.join(electronRoot, 'release')
const packageInfo = require(path.join(electronRoot, 'package.json'))
const verifiedRoot = path.join(releaseRoot, 'verified', packageInfo.version)

function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, {
    cwd: electronRoot,
    stdio: 'inherit',
    env: { ...process.env, ...extraEnv },
    shell: process.platform === 'win32',
  })
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with ${result.status}`)
  }
}

function output(command, args) {
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    encoding: 'utf8',
    env: process.env,
  })
  if (result.status !== 0) return ''
  return result.stdout.trim()
}

function cleanDirectory(target) {
  const resolved = path.resolve(target)
  if (!resolved.startsWith(path.resolve(releaseRoot) + path.sep)) {
    throw new Error(`Refusing to clean outside release root: ${resolved}`)
  }
  fs.rmSync(resolved, { recursive: true, force: true })
  if (fs.existsSync(resolved) && process.platform === 'win32') {
    const result = spawnSync(
      'powershell.exe',
      ['-NoProfile', '-Command',
        'Remove-Item -LiteralPath $env:MODAGENT_CLEAN_TARGET -Recurse -Force'],
      {
        stdio: 'inherit',
        env: { ...process.env, MODAGENT_CLEAN_TARGET: resolved },
      }
    )
    if (result.status !== 0 || fs.existsSync(resolved)) {
      throw new Error(`Could not clean release directory: ${resolved}`)
    }
  }
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function copyTree(source, target) {
  if (process.platform === 'win32') {
    const result = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        'Copy-Item -LiteralPath $env:MODAGENT_COPY_SOURCE -Destination $env:MODAGENT_COPY_TARGET -Recurse -Force',
      ],
      {
        stdio: 'inherit',
        env: {
          ...process.env,
          MODAGENT_COPY_SOURCE: source,
          MODAGENT_COPY_TARGET: target,
        },
      }
    )
    if (result.status !== 0 || !fs.existsSync(target)) {
      throw new Error(`Could not copy portable application to verified output: ${target}`)
    }
    return
  }
  fs.cpSync(source, target, { recursive: true })
}

function inspectAsar(edition) {
  const identity = edition === 'free'
    ? { folder: 'free', executable: 'ModAgent.exe', installer: `ModAgent-Setup-${packageInfo.version}.exe` }
    : { folder: 'subscription', executable: 'ModAgentP.exe', installer: `ModAgent-P-Setup-${packageInfo.version}.exe` }
  const appDir = path.join(releaseRoot, identity.folder, 'win-unpacked')
  const archive = path.join(appDir, 'resources', 'app.asar')
  const backend = path.join(appDir, 'resources', 'backend', 'ModAgentBackend.exe')
  const executable = path.join(appDir, identity.executable)
  const installer = path.join(releaseRoot, identity.folder, identity.installer)
  const legalDir = path.join(appDir, 'resources', 'legal')
  for (const required of [archive, backend, executable, installer]) {
    if (!fs.existsSync(required)) throw new Error(`${edition} artifact missing: ${required}`)
  }

  const entries = asar.listPackage(archive)
  for (const sourceFile of ['main.js', 'updater.js', 'runtimeDiagnostics.js']) {
    const packedText = asar.extractFile(archive, sourceFile).toString('utf8')
    if (/\?{4,}|\uFFFD/.test(packedText)) {
      throw new Error(`${edition} app.asar contains corrupted user text in ${sourceFile}`)
    }
  }
  const mp3 = entries.filter(entry => entry.toLowerCase().endsWith('.mp3'))
  const paidAssets = entries.filter(entry =>
    /(?:^|[\\/])assets[\\/](?:themes|audio|license)(?:[\\/]|$)|modagent-p\.(?:ico|png)$/i.test(entry)
  )
  const marker = JSON.parse(
    asar.extractFile(archive, 'dist\\edition.json').toString('utf8')
  )
  const packedPackage = JSON.parse(
    asar.extractFile(archive, 'package.json').toString('utf8')
  )
  if (marker.edition !== edition || marker.channel !== 'stable'
      || packedPackage.modagentEdition !== edition
      || packedPackage.modagentChannel !== 'stable') {
    throw new Error(`${edition} identity mismatch in packaged application`)
  }
  const expectedProductName = edition === 'free' ? 'ModAgent' : 'ModAgent P'
  if (packedPackage.productName !== expectedProductName) {
    throw new Error(`${edition} product name mismatch: ${packedPackage.productName}`)
  }
  if (edition === 'free' && (mp3.length || paidAssets.length)) {
    throw new Error(`Free build contains P assets: mp3=${mp3.length}, assets=${paidAssets.length}`)
  }
  if (edition === 'subscription' && mp3.length !== expectedAudioCount) {
    throw new Error(
      `Subscription build must contain exactly ${expectedAudioCount} verified sounds; found ${mp3.length}`
    )
  }
  const expectedIcon = edition === 'free' ? 'modagent-free.ico' : 'modagent-p.ico'
  if (!entries.some(entry => new RegExp(`assets[\\\\/]icons[\\\\/]${expectedIcon.replace('.', '\\.')}$`, 'i').test(entry))) {
    throw new Error(`${edition} build is missing ${expectedIcon}`)
  }
  const hasPublicKey = entries.some(entry => /assets[\\/]license[\\/]p-public-key\.pem$/i.test(entry))
  if (edition === 'free' && hasPublicKey) {
    throw new Error('Free build contains the P license public key')
  }
  if (edition === 'subscription' && !hasPublicKey) {
    throw new Error('P build is missing the license public key')
  }
  const legalFiles = fs.readdirSync(legalDir).sort()
  const subscriptionLegal = legalFiles.filter(file =>
    /SUBSCRIPTION|PROPRIETARY/i.test(file)
  )
  if (edition === 'free' && subscriptionLegal.length) {
    throw new Error(`Free build contains subscription legal files: ${subscriptionLegal.join(', ')}`)
  }
  if (edition === 'subscription' && subscriptionLegal.length !== 3) {
    throw new Error(`Subscription build legal set is incomplete: ${subscriptionLegal.join(', ')}`)
  }

  return {
    edition,
    marker,
    mp3Count: mp3.length,
    paidAssetCount: paidAssets.length,
    legalFiles,
    installer,
    executable,
    backend,
    installerSha256: sha256(installer),
    executableSha256: sha256(executable),
    backendSha256: sha256(backend),
  }
}

const commit = output('git', ['-c', `safe.directory=${repoRoot.replaceAll('\\', '/')}`, 'rev-parse', 'HEAD'])
const statusLines = output(
  'git',
  ['-c', `safe.directory=${repoRoot.replaceAll('\\', '/')}`, 'status', '--porcelain']
).split(/\r?\n/).filter(Boolean)
const generatedPath = /(?:^|\/)(?:__pycache__|electron\/dist|electron\/release|build)(?:\/|$)|\.pyc$/i
const untrackedReleaseSource = /^(?:electron|modagent|packaging|tools|updates)\//i
const relevantDirtyLines = statusLines.filter(line => {
  const sourcePath = line.slice(3).replaceAll('\\', '/')
  if (generatedPath.test(sourcePath)) return false
  return !line.startsWith('?? ') || untrackedReleaseSource.test(sourcePath)
})
const dirty = relevantDirtyLines.length > 0
if (dirty && process.env.MODAGENT_ALLOW_DIRTY !== '1') {
  throw new Error(
    `Refusing release from a dirty worktree:\n${relevantDirtyLines.join('\n')}\n` +
    'Commit first or set MODAGENT_ALLOW_DIRTY=1 for local validation.'
  )
}

const reports = []
if (process.env.MODAGENT_SKIP_BUILD !== '1') {
  cleanDirectory(verifiedRoot)
  if (process.env.MODAGENT_SKIP_BACKEND_BUILD !== '1') {
    run('npm.cmd', ['run', 'build:backend'])
  }
  for (const edition of ['free', 'subscription']) {
    cleanDirectory(path.join(releaseRoot, edition))
    run('npm.cmd', ['run', 'build'], {
      MODAGENT_EDITION: edition,
      MODAGENT_CHANNEL: 'stable',
    })
    run('npx.cmd', [
      'electron-builder', '--win', 'nsis',
      '--config', 'electron-builder.config.cjs',
    ], { MODAGENT_EDITION: edition, MODAGENT_CHANNEL: 'stable' })
  }
} else {
  cleanDirectory(verifiedRoot)
}
for (const edition of ['free', 'subscription']) {
  const report = inspectAsar(edition)
  run('node', [
    'scripts/test-packaged-smoke.js',
    '--exe', report.executable,
    '--edition', edition,
  ])
  reports.push(report)
}

fs.mkdirSync(verifiedRoot, { recursive: true })
for (const report of reports) {
  const target = path.join(verifiedRoot, path.basename(report.installer))
  fs.copyFileSync(report.installer, target)
  report.verifiedInstaller = target
}
for (const manifestName of ['free-update.json', 'p-update.json']) {
  fs.copyFileSync(
    path.join(repoRoot, 'updates', manifestName),
    path.join(verifiedRoot, manifestName),
  )
}
const proReport = reports.find(item => item.edition === 'subscription')
const proPortable = path.join(verifiedRoot, 'ModAgentP')
copyTree(path.dirname(proReport.executable), proPortable)

const manifest = {
  schema: 1,
  version: packageInfo.version,
  commit,
  dirty,
  builtAt: new Date().toISOString(),
  sourceRoot: repoRoot,
  reports: reports.map(report => ({
    edition: report.edition,
    marker: report.marker,
    mp3Count: report.mp3Count,
    paidAssetCount: report.paidAssetCount,
    legalFiles: report.legalFiles,
    installer: path.basename(report.verifiedInstaller),
    installerSha256: report.installerSha256,
    executableSha256: report.executableSha256,
    backendSha256: report.backendSha256,
  })),
}
fs.writeFileSync(
  path.join(verifiedRoot, 'release-manifest.json'),
  JSON.stringify(manifest, null, 2)
)
console.log(`Verified release ready: ${verifiedRoot}`)
