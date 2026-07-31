const assert = require('assert')
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const root = path.resolve(__dirname, '..')
const markerPath = path.join(root, 'dist', 'edition.json')
const previous = fs.existsSync(markerPath) ? fs.readFileSync(markerPath) : null

function loadConfig(edition, channel) {
  const script = [
    `process.env.MODAGENT_EDITION=${JSON.stringify(edition)};`,
    `process.env.MODAGENT_CHANNEL=${JSON.stringify(channel)};`,
    "require('./electron-builder.config.cjs');",
  ].join('')
  return spawnSync(process.execPath, ['-e', script], {
    cwd: root,
    encoding: 'utf8',
  })
}

try {
  fs.mkdirSync(path.dirname(markerPath), { recursive: true })
  fs.writeFileSync(markerPath, JSON.stringify({
    edition: 'subscription',
    channel: 'beta',
    version: '1.3.0',
  }))

  const matching = loadConfig('subscription', 'beta')
  assert.strictEqual(matching.status, 0, matching.stderr)

  const mixed = loadConfig('subscription', 'stable')
  assert.notStrictEqual(mixed.status, 0)
  assert.match(mixed.stderr, /Refusing mixed build/)
  console.log('BUILDER IDENTITY GUARD PASS')
} finally {
  if (previous === null) {
    fs.rmSync(markerPath, { force: true })
  } else {
    fs.writeFileSync(markerPath, previous)
  }
}
