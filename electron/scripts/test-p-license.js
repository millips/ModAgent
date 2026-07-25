const assert = require('assert')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { createLicenseStore, DAY_MS } = require('../licenseStore')

const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-license-test-'))
const publicKeyPath = path.join(temp, 'public.pem')
fs.writeFileSync(publicKeyPath, publicKey.export({ type: 'spki', format: 'pem' }))
let currentTime = Date.UTC(2026, 6, 26)
const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: value => Buffer.from(value, 'utf8'),
  decryptString: value => value.toString('utf8'),
}

function token(id, days = 60) {
  const payload = Buffer.from(JSON.stringify({
    v: 1, product: 'modagent-p', id, days, batch: 'test',
  })).toString('base64url')
  const signature = crypto.sign(null, Buffer.from(payload), privateKey).toString('base64url')
  return `MAP1.${payload}.${signature}`
}

try {
  const store = createLicenseStore({
    dataDir: temp,
    edition: 'subscription',
    safeStorage,
    publicKeyPath,
    now: () => currentTime,
  })
  assert.strictEqual(store.status().state, 'trial')
  currentTime += 3 * DAY_MS + 1
  assert.strictEqual(store.status().state, 'trial_expired')
  const active = store.activate(token('launch_license_001'))
  assert.strictEqual(active.state, 'active')
  assert.strictEqual(active.duration_days, 60)
  currentTime += 60 * DAY_MS + 1
  assert.strictEqual(store.status().state, 'expired')
  const renewed = store.activate(token('renew_license_002'))
  assert.strictEqual(renewed.state, 'active')
  assert.throws(() => store.activate('MAP1.invalid.invalid'))
  console.log('P LICENSE TESTS PASSED')
} finally {
  fs.rmSync(temp, { recursive: true, force: true })
}
