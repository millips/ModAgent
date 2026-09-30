// A diagnostic reproduction, not a passing product acceptance test.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
if (!process.versions.electron) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-crypto-context-test-'))
  const run = (operation, profile) => spawnSync(require('electron'), [__filename, operation, path.join(root, profile), path.join(root, 'fake-cipher.json')], { encoding: 'utf8', windowsHide: true, timeout: 15000 })
  const encrypted = run('encrypt', 'A')
  const same = run('decrypt', 'A')
  const other = run('decrypt', 'B')
  const source = JSON.parse(fs.readFileSync(path.join(root, 'A/Local State'), 'utf8'))
  fs.mkdirSync(path.join(root, 'C'), { recursive: true })
  fs.writeFileSync(path.join(root, 'C/Local State'), JSON.stringify({ os_crypt: source.os_crypt }))
  const isolatedContext = run('decrypt', 'C')
  const succeeded = result => String(result.stdout).includes('"verified":true')
  const report = { fake_credentials_only: true, encrypt_ok: succeeded(encrypted), same_profile_ok: succeeded(same),
    different_profile_ok: succeeded(other), isolated_matching_crypto_context_ok: succeeded(isolatedContext),
    product_cross_profile_acceptance: succeeded(other) }
  console.log(JSON.stringify(report))
  const output = path.resolve(__dirname, '../../build/conversation-flow-20260906-r4/cross-profile-credentials.json')
  fs.writeFileSync(output, JSON.stringify(report, null, 2))
  if (!succeeded(encrypted) || !succeeded(same) || !succeeded(isolatedContext)) process.exit(1)
} else {
  const { app, safeStorage } = require('electron')
  const [operation, profile, file] = process.argv.slice(2)
  app.setPath('userData', profile)
  app.whenReady().then(() => {
    let verified = true
    if (operation === 'encrypt') fs.writeFileSync(file, JSON.stringify({ encrypted: safeStorage.encryptString('FAKE-cross-profile-credential').toString('base64') }))
    else {
      try {
        const envelope = JSON.parse(fs.readFileSync(file, 'utf8'))
        if (safeStorage.decryptString(Buffer.from(envelope.encrypted, 'base64')) !== 'FAKE-cross-profile-credential') throw Error()
      } catch (_) { verified = false }
    }
    console.log(JSON.stringify({ verified }))
    app.quit()
  }).catch(() => { process.exitCode = 1; app.quit() })
}
