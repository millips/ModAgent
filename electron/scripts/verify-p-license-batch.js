const assert = require('assert')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

function option(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : ''
}

const publicKeyPath = path.resolve(option('--public-key'))
const ledgerPath = path.resolve(option('--ledger'))
if (!option('--public-key') || !option('--ledger')) {
  throw new Error('Usage: node verify-p-license-batch.js --public-key <public.pem> --ledger <ledger.json>')
}

const publicKey = fs.readFileSync(publicKeyPath, 'utf8')
const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8').replace(/^\uFEFF/, ''))
assert.strictEqual(ledger.schema, 1)
assert.strictEqual(ledger.product, 'modagent-p')
assert(Array.isArray(ledger.licenses) && ledger.licenses.length > 0)

const ids = new Set()
for (const row of ledger.licenses) {
  assert(!ids.has(row.license_id), `Duplicate license id: ${row.license_id}`)
  ids.add(row.license_id)
  const parts = String(row.token || '').split('.')
  assert.strictEqual(parts.length, 3)
  assert.strictEqual(parts[0], 'MAP1')
  const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
  assert.strictEqual(payload.product, 'modagent-p')
  assert.strictEqual(payload.id, row.license_id)
  if (ledger.entitlement === 'permanent') {
    assert.strictEqual(payload.entitlement, 'permanent')
    assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, 'days'), false)
    assert.strictEqual(row.entitlement, 'permanent')
    assert.strictEqual(row.duration_days, null)
  } else {
    assert.strictEqual(payload.entitlement, undefined)
    assert.strictEqual(payload.days, ledger.duration_days)
    assert.strictEqual(row.duration_days, ledger.duration_days)
  }
  assert.strictEqual(
    crypto.verify(null, Buffer.from(parts[1], 'utf8'), publicKey, Buffer.from(parts[2], 'base64url')),
    true,
    `Invalid signature for ${row.license_id}`,
  )
}

console.log(`Verified ${ledger.licenses.length} signed ModAgent P license codes.`)
