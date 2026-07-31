const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const { spawnSync } = require('child_process')

const electronRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(electronRoot, '..')
const packageInfo = require(path.join(electronRoot, 'package.json'))
const releaseRoot = path.join(electronRoot, 'release')
const verifiedRoot = path.join(releaseRoot, 'verified', packageInfo.version)
const targetRoot = path.join(releaseRoot, 'afdian-p', `v${packageInfo.version}`)
const manifestPath = path.join(verifiedRoot, 'release-manifest.json')

if (!fs.existsSync(manifestPath)) {
  throw new Error('Verified release manifest missing; run npm run release:all first')
}
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
if (manifest.dirty) throw new Error('Refusing to prepare AFDIAN package from a dirty release')
const report = manifest.reports?.find(item => item.edition === 'subscription')
if (!report) throw new Error('Verified P report missing')

const resolved = path.resolve(targetRoot)
if (!resolved.startsWith(path.resolve(releaseRoot) + path.sep)) {
  throw new Error(`Refusing to modify outside release root: ${resolved}`)
}
fs.rmSync(resolved, { recursive: true, force: true })
fs.mkdirSync(resolved, { recursive: true })

function copy(source, targetName = path.basename(source)) {
  if (!fs.existsSync(source)) throw new Error(`Release file missing: ${source}`)
  fs.copyFileSync(source, path.join(resolved, targetName))
}

function sha256(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function createPortableZip(source, destination) {
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
        MODAGENT_PORTABLE_ZIP: destination,
      },
    },
  )
  if (result.status !== 0 || !fs.existsSync(destination)) {
    throw new Error(`Could not create P portable archive: ${destination}`)
  }
}

copy(path.join(verifiedRoot, report.installer))
copy(path.join(verifiedRoot, manifest.cleanupTool.file))
copy(path.join(verifiedRoot, 'p-update.json'))
copy(path.join(repoRoot, 'docs', 'MODAGENT-P-MEMBERSHIP-GUIDE.md'), 'ModAgent-P-会员教程.md')
copy(path.join(repoRoot, 'docs', `USER-GUIDE-v${packageInfo.version}.md`), '使用教程.md')
copy(path.join(repoRoot, 'docs', `RELEASE-SECURITY-REVIEW-v${packageInfo.version}.md`), '发行安全审查.md')
copy(path.join(repoRoot, 'docs', 'AFDIAN-P-LAUNCH-2026-07-26.md'), '爱发电发布文案.md')

const portableName = `ModAgent-P-Portable-${packageInfo.version}.zip`
const portablePath = path.join(resolved, portableName)
createPortableZip(path.join(verifiedRoot, 'ModAgentP'), portablePath)
const portableSha256 = sha256(portablePath)

fs.writeFileSync(
  path.join(resolved, 'SHA256SUMS.txt'),
  [
    `${report.installerSha256}  ${report.installer}`,
    `${portableSha256}  ${portableName}`,
    `${manifest.cleanupTool.sha256}  ${manifest.cleanupTool.file}`,
  ].join('\n') + '\n',
  'utf8',
)
fs.writeFileSync(
  path.join(resolved, '上传前说明.txt'),
  [
    `ModAgent P v${packageInfo.version} 爱发电私有发布目录`,
    `源码提交：${manifest.commit}`,
    'P 安装包不得作为公开 GitHub Release 附件。',
    '兑换码和签发私钥不在本目录；请通过爱发电 Bot 单独、安全地发放兑换码。',
    '上传前再次核对 SHA256，并在爱发电页面注明当前安装包未做商业代码签名。',
  ].join('\r\n') + '\r\n',
  'utf8',
)

console.log(`AFDIAN P package ready: ${resolved}`)
