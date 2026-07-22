const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const electronRoot = path.resolve(__dirname, '..')
const dist = path.resolve(electronRoot, 'dist')
if (path.dirname(dist) !== electronRoot || path.basename(dist) !== 'dist') {
  throw new Error(`Refusing to clean unexpected path: ${dist}`)
}
fs.rmSync(dist, { recursive: true, force: true })
if (fs.existsSync(dist) && process.platform === 'win32') {
  const result = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-Command',
      'Remove-Item -LiteralPath $env:MODAGENT_CLEAN_TARGET -Recurse -Force'],
    {
      stdio: 'inherit',
      env: { ...process.env, MODAGENT_CLEAN_TARGET: dist },
    }
  )
  if (result.status !== 0) {
    throw new Error(`PowerShell could not clean build output: ${dist}`)
  }
}
if (fs.existsSync(dist)) {
  throw new Error(`Build output still exists after cleanup: ${dist}`)
}
console.log(`Cleaned build output: ${dist}`)
