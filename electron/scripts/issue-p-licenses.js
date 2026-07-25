const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

function option(name, fallback = '') {
  const index = process.argv.indexOf(name)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const privateKeyPath = path.resolve(option('--private-key'))
const outputDir = path.resolve(option('--output'))
const count = Number(option('--count', '1'))
const days = Number(option('--days', '60'))
const batch = option('--batch', new Date().toISOString().slice(0, 10))
if (!option('--private-key') || !option('--output')) {
  throw new Error('Usage: node issue-p-licenses.js --private-key <private.pem> --output <folder> [--count 100] [--days 60] [--batch launch]')
}
if (!Number.isInteger(count) || count < 1 || count > 10000) throw new Error('count must be 1..10000')
if (!Number.isInteger(days) || days < 1 || days > 366) throw new Error('days must be 1..366')

const privateKey = fs.readFileSync(privateKeyPath, 'utf8')
const rows = []
for (let index = 0; index < count; index += 1) {
  const payload = {
    v: 1,
    product: 'modagent-p',
    id: crypto.randomBytes(12).toString('base64url'),
    days,
    batch,
  }
  const encodedPayload = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url')
  const signature = crypto.sign(null, Buffer.from(encodedPayload, 'utf8'), privateKey).toString('base64url')
  rows.push({
    license_id: payload.id,
    batch,
    duration_days: days,
    issued: false,
    order_reference: '',
    token: `MAP1.${encodedPayload}.${signature}`,
  })
}

fs.mkdirSync(outputDir, { recursive: true })
const base = `modagent-p-${batch}-${days}d`
const codesPath = path.join(outputDir, `${base}-codes.txt`)
const ledgerPath = path.join(outputDir, `${base}-ledger.json`)
if (fs.existsSync(codesPath) || fs.existsSync(ledgerPath)) {
  throw new Error(`Refusing to overwrite an existing license batch: ${base}`)
}
fs.writeFileSync(codesPath, rows.map(row => row.token).join('\n') + '\n', { encoding: 'utf8', flag: 'wx' })
fs.writeFileSync(ledgerPath, JSON.stringify({
  schema: 1,
  product: 'modagent-p',
  duration_days: days,
  batch,
  generated_at: new Date().toISOString(),
  licenses: rows,
}, null, 2), { encoding: 'utf8', flag: 'wx' })
console.log(`Issued ${count} signed ModAgent P license codes in ${outputDir}`)
