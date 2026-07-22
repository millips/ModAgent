const crypto = require('crypto')
const { spawnSync } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const electronRoot = path.resolve(__dirname, '..')
const packageInfo = require(path.join(electronRoot, 'package.json'))
const verifiedRoot = path.join(electronRoot, 'release', 'verified', packageInfo.version)
const manifestPath = path.join(verifiedRoot, 'release-manifest.json')
const desktop = path.join(os.homedir(), 'Desktop')
const freeName = 'ModAgent \u666e\u901a\u7248'
const proName = 'ModAgent \u8ba2\u9605\u7248'
const freeTarget = process.env.MODAGENT_FREE_TARGET || path.join(desktop, freeName)
const proTarget = process.env.MODAGENT_PRO_TARGET || path.join(desktop, proName)

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function assertSafeTarget(target, expectedName) {
  const resolved = path.resolve(target)
  if (path.basename(resolved) !== expectedName || path.dirname(resolved) !== desktop) {
    throw new Error(`Refusing unexpected promotion target: ${resolved}`)
  }
  return resolved
}

function copyVerified(source, target, expectedHash) {
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.copyFileSync(source, target)
  const actualHash = sha256(target)
  if (actualHash !== expectedHash) {
    throw new Error(`Hash mismatch after promotion: ${target}`)
  }
}

function replaceTree(source, target) {
  if (process.platform === 'win32') {
    const result = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        [
          'if (Test-Path -LiteralPath $env:MODAGENT_COPY_TARGET) {',
          '  Remove-Item -LiteralPath $env:MODAGENT_COPY_TARGET -Recurse -Force',
          '}',
          'Copy-Item -LiteralPath $env:MODAGENT_COPY_SOURCE -Destination $env:MODAGENT_COPY_TARGET -Recurse -Force',
        ].join('; '),
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
      throw new Error(`Could not replace desktop portable directory: ${target}`)
    }
    return
  }
  fs.rmSync(target, { recursive: true, force: true })
  fs.cpSync(source, target, { recursive: true })
}

if (!fs.existsSync(manifestPath)) {
  throw new Error(`Verified release manifest not found: ${manifestPath}`)
}
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
if (manifest.dirty) {
  throw new Error('Refusing to promote a release built from uncommitted source changes.')
}

const freeDir = assertSafeTarget(freeTarget, freeName)
const proDir = assertSafeTarget(proTarget, proName)
const free = manifest.reports.find(report => report.edition === 'free')
const subscription = manifest.reports.find(report => report.edition === 'subscription')
if (!free || !subscription) throw new Error('Verified manifest does not contain both editions.')

copyVerified(
  path.join(verifiedRoot, free.installer),
  path.join(freeDir, free.installer),
  free.installerSha256
)
copyVerified(
  path.join(verifiedRoot, subscription.installer),
  path.join(proDir, subscription.installer),
  subscription.installerSha256
)

const portableSource = path.join(verifiedRoot, 'ModAgentPro')
const portableTarget = path.join(proDir, 'ModAgentPro')
replaceTree(portableSource, portableTarget)
const promotedExecutable = path.join(portableTarget, 'ModAgentPro.exe')
if (sha256(promotedExecutable) !== subscription.executableSha256) {
  throw new Error('Portable subscription executable hash mismatch after promotion.')
}

fs.copyFileSync(manifestPath, path.join(freeDir, 'release-manifest.json'))
fs.copyFileSync(manifestPath, path.join(proDir, 'release-manifest.json'))
console.log(`Promoted verified ${manifest.version} release to desktop.`)
