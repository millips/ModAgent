const { spawnSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const asar = require('@electron/asar')

const electronRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(electronRoot, '..')
const releaseRoot = path.join(electronRoot, 'release')
const freeRoot = path.join(releaseRoot, 'free')
const packageInfo = require(path.join(electronRoot, 'package.json'))
const candidateRoot = path.join(
  releaseRoot,
  'github-free',
  `v${packageInfo.version}-candidate`
)

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
  return result.status === 0 ? result.stdout.replace(/\s+$/, '') : ''
}

function assertInsideRelease(target) {
  const resolved = path.resolve(target)
  const prefix = path.resolve(releaseRoot) + path.sep
  if (!resolved.startsWith(prefix)) {
    throw new Error(`Refusing to modify outside release root: ${resolved}`)
  }
  return resolved
}

function cleanDirectory(target) {
  const resolved = assertInsideRelease(target)
  fs.rmSync(resolved, { recursive: true, force: true })
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function fileSize(file) {
  return fs.statSync(file).size
}

function createPortableZip(source, destination) {
  const resolvedDestination = assertInsideRelease(destination)
  fs.rmSync(resolvedDestination, { force: true })
  const result = spawnSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-Command',
      'Compress-Archive -Path (Join-Path $env:MODAGENT_PORTABLE_SOURCE "*") -DestinationPath $env:MODAGENT_PORTABLE_ZIP -CompressionLevel Optimal -Force',
    ],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        MODAGENT_PORTABLE_SOURCE: source,
        MODAGENT_PORTABLE_ZIP: resolvedDestination,
      },
    }
  )
  if (result.status !== 0 || !fs.existsSync(resolvedDestination)) {
    throw new Error(`Could not create portable archive: ${resolvedDestination}`)
  }
}

function inspectFreeBuild() {
  const appDir = path.join(freeRoot, 'win-unpacked')
  const archive = path.join(appDir, 'resources', 'app.asar')
  const backend = path.join(appDir, 'resources', 'backend', 'ModAgentBackend.exe')
  const executable = path.join(appDir, 'ModAgent.exe')
  const installer = path.join(freeRoot, `ModAgent-Setup-${packageInfo.version}.exe`)
  const legalDir = path.join(appDir, 'resources', 'legal')

  for (const required of [archive, backend, executable, installer, legalDir]) {
    if (!fs.existsSync(required)) throw new Error(`Free artifact missing: ${required}`)
  }

  const entries = asar.listPackage(archive)
  for (const sourceFile of ['main.js', 'updater.js', 'runtimeDiagnostics.js']) {
    const packedText = asar.extractFile(archive, sourceFile).toString('utf8')
    if (/\?{4,}|\uFFFD/.test(packedText)) {
      throw new Error(`Free app.asar contains corrupted user text in ${sourceFile}`)
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
  if (marker.edition !== 'free' || packedPackage.modagentEdition !== 'free') {
    throw new Error('Packaged application is not identified as the free edition')
  }
  if (packedPackage.productName !== 'ModAgent') {
    throw new Error(`Unexpected free product name: ${packedPackage.productName}`)
  }
  if (!entries.some(entry => /assets[\\/]icons[\\/]modagent-free\.ico$/i.test(entry))) {
    throw new Error('Free build is missing its program icon')
  }
  if (mp3.length || paidAssets.length) {
    throw new Error(
      `Free build contains P assets: mp3=${mp3.length}, assets=${paidAssets.length}`
    )
  }

  const legalFiles = fs.readdirSync(legalDir).sort()
  const forbiddenLegal = legalFiles.filter(file =>
    /SUBSCRIPTION|PROPRIETARY/i.test(file)
  )
  if (forbiddenLegal.length) {
    throw new Error(
      `Free build contains subscription legal files: ${forbiddenLegal.join(', ')}`
    )
  }
  for (const required of [
    'LICENSE-GPL-3.0.txt',
    'LICENSE.md',
    'PRIVACY.md',
    'THIRD-PARTY-MODS-DISCLAIMER.md',
    'THIRD_PARTY_NOTICES.md',
  ]) {
    if (!legalFiles.includes(required)) {
      throw new Error(`Free legal set is incomplete: missing ${required}`)
    }
  }

  return {
    appDir,
    installer,
    executable,
    backend,
    marker,
    packedPackage: {
      productName: packedPackage.productName,
      modagentEdition: packedPackage.modagentEdition,
      version: packedPackage.version,
    },
    mp3Count: mp3.length,
    paidAssetCount: paidAssets.length,
    legalFiles,
  }
}

function copyIfExists(source, destination) {
  if (fs.existsSync(source)) fs.copyFileSync(source, destination)
}

const safeRepo = repoRoot.replaceAll('\\', '/')
const commit = output('git', ['-c', `safe.directory=${safeRepo}`, 'rev-parse', 'HEAD'])
const statusLines = output(
  'git',
  ['-c', `safe.directory=${safeRepo}`, '-c', 'core.quotePath=false', 'status', '--porcelain']
).split(/\r?\n/).filter(Boolean)
const generatedPath = /(?:^|\/)(?:__pycache__|electron\/dist|electron\/release|build)(?:\/|$)|\.pyc$/i
const relevantDirtyLines = statusLines.filter(
  line => !generatedPath.test(line.slice(3).replaceAll('\\', '/'))
)
const dirty = relevantDirtyLines.length > 0

if (process.env.MODAGENT_SKIP_BUILD !== '1') {
  cleanDirectory(freeRoot)
  if (process.env.MODAGENT_SKIP_BACKEND_BUILD !== '1') {
    run('npm.cmd', ['run', 'build:backend'])
  }
  run('npm.cmd', ['run', 'build'], { MODAGENT_EDITION: 'free' })
  run(
    'npx.cmd',
    ['electron-builder', '--win', 'nsis', '--config', 'electron-builder.config.cjs'],
    { MODAGENT_EDITION: 'free' }
  )
}

const report = inspectFreeBuild()
cleanDirectory(candidateRoot)
fs.mkdirSync(candidateRoot, { recursive: true })

const installerTarget = path.join(candidateRoot, path.basename(report.installer))
fs.copyFileSync(report.installer, installerTarget)

let portableTarget = null
if (process.env.MODAGENT_SKIP_PORTABLE !== '1') {
  portableTarget = path.join(
    candidateRoot,
    `ModAgent-Portable-${packageInfo.version}.zip`
  )
  createPortableZip(report.appDir, portableTarget)
}

copyIfExists(
  path.join(repoRoot, 'docs', 'releases', `v${packageInfo.version}-free.md`),
  path.join(candidateRoot, 'GitHub-Release-Notes.md')
)
copyIfExists(
  path.join(repoRoot, 'docs', 'MODAGENT-FREE-LAUNCH-PLAN.md'),
  path.join(candidateRoot, 'Promotion-Plan.md')
)
copyIfExists(
  path.join(repoRoot, 'README.md'),
  path.join(candidateRoot, 'README.md')
)
copyIfExists(
  path.join(repoRoot, 'updates', 'free-update.json'),
  path.join(candidateRoot, 'free-update.json')
)

const artifacts = [
  {
    type: 'installer',
    file: path.basename(installerTarget),
    bytes: fileSize(installerTarget),
    sha256: sha256(installerTarget),
  },
]
if (portableTarget) {
  artifacts.push({
    type: 'portable',
    file: path.basename(portableTarget),
    bytes: fileSize(portableTarget),
    sha256: sha256(portableTarget),
  })
}

const manifest = {
  schema: 1,
  releaseStatus: dirty ? 'candidate-dirty-worktree' : 'candidate-clean-worktree',
  publishReady: !dirty,
  edition: 'free',
  version: packageInfo.version,
  commit,
  dirty,
  dirtyFiles: relevantDirtyLines.map(line => line.slice(3).replaceAll('\\', '/')),
  builtAt: new Date().toISOString(),
  identity: report.packedPackage,
  isolationChecks: {
    editionMarker: report.marker,
    subscriptionAudioCount: report.mp3Count,
    pAssetCount: report.paidAssetCount,
    legalFiles: report.legalFiles,
  },
  componentHashes: {
    executableSha256: sha256(report.executable),
    backendSha256: sha256(report.backend),
  },
  artifacts,
}
fs.writeFileSync(
  path.join(candidateRoot, 'release-manifest.json'),
  JSON.stringify(manifest, null, 2) + '\n',
  'utf8'
)
fs.writeFileSync(
  path.join(candidateRoot, 'SHA256SUMS.txt'),
  artifacts.map(item => `${item.sha256}  ${item.file}`).join('\n') + '\n',
  'utf8'
)
fs.writeFileSync(
  path.join(candidateRoot, '发布状态.txt'),
  [
    `ModAgent ${packageInfo.version} 普通版 GitHub 发布候选包`,
    `状态：${manifest.releaseStatus}`,
    dirty
      ? '注意：该包来自尚未提交的当前工作树，可用于测试和内容确认；正式发布前应提交源码并重新构建。'
      : '当前源码树干净，候选包可进入最终烟雾测试与 GitHub Release 上传流程。',
    '普通版隔离检查：通过（无 P 音效、主题素材、许可证公钥或 P 图标）。',
  ].join('\r\n') + '\r\n',
  'utf8'
)

console.log(`GitHub free candidate ready: ${candidateRoot}`)
console.log(`Publish ready: ${manifest.publishReady}`)
