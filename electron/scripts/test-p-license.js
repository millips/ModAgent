const assert = require('assert')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { createLicenseStore, DAY_MS, canUsePBenefits } = require('../licenseStore')

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

function token(id, days = 60, contentPacks = []) {
  const payload = Buffer.from(JSON.stringify({
    v: 1, product: 'modagent-p', id, days, batch: 'test',
    ...(contentPacks.length ? { content_packs: contentPacks } : {}),
  })).toString('base64url')
  const signature = crypto.sign(null, Buffer.from(payload), privateKey).toString('base64url')
  return `MAP1.${payload}.${signature}`
}

function permanentToken(id) {
  const payload = Buffer.from(JSON.stringify({
    v: 1, product: 'modagent-p', id, entitlement: 'permanent', batch: 'test',
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
  assert.strictEqual(store.status().state, 'trial_available')
  assert.strictEqual(fs.existsSync(store.licenseFile), false)
  const trial = store.startTrial()
  assert.strictEqual(trial.state, 'trial')
  assert.strictEqual(trial.days_remaining, 3)
  assert.strictEqual(fs.existsSync(store.licenseFile), true)
  currentTime += 3 * DAY_MS + 1
  assert.strictEqual(store.status().state, 'trial_expired')
  const active = store.activate(token('launch_license_001'))
  assert.strictEqual(active.state, 'active')
  assert.strictEqual(active.duration_days, 60)
  assert.strictEqual(canUsePBenefits(active), true)
  assert.deepStrictEqual(active.content_packs, ['legacy-collection-2026'])
  currentTime += 60 * DAY_MS + 1
  const expired = store.status()
  assert.strictEqual(expired.state, 'expired')
  assert.strictEqual(canUsePBenefits(expired), false)
  assert.deepStrictEqual(expired.content_packs, ['legacy-collection-2026'])
  const renewed = store.activate(token('renew_license_002'))
  assert.strictEqual(renewed.state, 'active')
  const permanent = store.activate(permanentToken('owner_permanent_001'))
  assert.strictEqual(permanent.state, 'permanent')
  assert.strictEqual(permanent.entitled, true)
  assert.strictEqual(permanent.permanent, true)
  assert.strictEqual(permanent.expires_at, null)
  assert.strictEqual(canUsePBenefits(permanent), true)
  currentTime += 100 * 365 * DAY_MS
  assert.strictEqual(store.status().state, 'permanent')
  assert.strictEqual(store.status().entitled, true)
  assert.strictEqual(store.activate(token('fixed_after_permanent')).state, 'permanent')
  assert.strictEqual(canUsePBenefits({ edition: 'free', entitled: true }), false)
  assert.throws(() => store.activate('MAP1.invalid.invalid'))

  const packDir = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-content-pack-test-'))
  const packPublicKeyPath = path.join(packDir, 'public.pem')
  fs.writeFileSync(packPublicKeyPath, publicKey.export({ type: 'spki', format: 'pem' }))
  const packStore = createLicenseStore({ dataDir: packDir, edition: 'subscription', safeStorage, publicKeyPath: packPublicKeyPath, now: () => currentTime })
  const monthly = packStore.activate(token('monthly_pack_001', 30, ['wallpapers-2026-09']))
  assert.deepStrictEqual(monthly.content_packs, ['wallpapers-2026-09'])
  currentTime += 30 * DAY_MS + 1
  const monthlyExpired = packStore.status()
  assert.strictEqual(monthlyExpired.state, 'expired')
  assert.deepStrictEqual(monthlyExpired.content_packs, ['wallpapers-2026-09'])
  fs.rmSync(packDir, { recursive: true, force: true })

  // An unreadable encrypted envelope stays untouched by status(), and can be
  // recovered only after a valid signed code is submitted.
  const recoveryDir = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-license-recovery-'))
  const recoveryPublicKeyPath = path.join(recoveryDir, 'public.pem')
  fs.writeFileSync(recoveryPublicKeyPath, publicKey.export({ type: 'spki', format: 'pem' }))
  let unreadable = true
  const recoveryStorage = {
    isEncryptionAvailable: () => true,
    encryptString: value => Buffer.from(value, 'utf8'),
    decryptString: value => {
      if (unreadable) throw new Error('simulated unreadable envelope')
      return value.toString('utf8')
    },
  }
  const recoveryStore = createLicenseStore({
    dataDir: recoveryDir,
    edition: 'subscription',
    safeStorage: recoveryStorage,
    publicKeyPath: recoveryPublicKeyPath,
    now: () => currentTime,
  })
  const recoveryFile = path.join(recoveryDir, 'editions', 'subscription', 'license.dat')
  fs.mkdirSync(path.dirname(recoveryFile), { recursive: true })
  fs.writeFileSync(recoveryFile, JSON.stringify({ version: 1, protected: 'not-readable' }))
  assert.strictEqual(recoveryStore.status().state, 'invalid')
  unreadable = false
  const recovered = recoveryStore.activate(permanentToken('recovered_owner_license'))
  assert.strictEqual(recovered.state, 'permanent')
  assert.ok(fs.readdirSync(path.dirname(recoveryFile)).some(name => name.includes('.unreadable-')))
  fs.rmSync(recoveryDir, { recursive: true, force: true })
  console.log('P LICENSE TESTS PASSED')
} finally {
  fs.rmSync(temp, { recursive: true, force: true })
}
