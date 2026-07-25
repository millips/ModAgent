const crypto = require('crypto')
const fs = require('fs')
const path = require('path')

function option(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : ''
}

const privateOutput = path.resolve(option('--private-output') || '')
const publicOutput = path.resolve(option('--public-output') || '')
if (!option('--private-output') || !option('--public-output')) {
  throw new Error('Usage: node generate-p-license-keypair.js --private-output <outside-repo.pem> --public-output <p-public-key.pem>')
}
if (fs.existsSync(privateOutput) || fs.existsSync(publicOutput)) {
  throw new Error('Refusing to overwrite an existing license key')
}

const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
fs.mkdirSync(path.dirname(privateOutput), { recursive: true })
fs.mkdirSync(path.dirname(publicOutput), { recursive: true })
fs.writeFileSync(privateOutput, privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 })
fs.writeFileSync(publicOutput, publicKey.export({ type: 'spki', format: 'pem' }))
console.log(`Private signing key created outside the repository: ${privateOutput}`)
console.log(`Public verification key created: ${publicOutput}`)
