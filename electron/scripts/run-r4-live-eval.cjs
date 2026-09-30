// Read encrypted credentials in memory; never print, export to disk, or alter them.
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { spawn, spawnSync } = require('node:child_process')
if (!process.versions.electron) {
  const child = spawnSync(require('electron'), [__filename], { windowsHide: true, encoding: 'utf8', timeout: 480000 })
  process.stdout.write(child.stdout || '')
  process.stderr.write(child.stderr || '')
  if (child.error) throw child.error
  process.exit(child.status || 0)
} else {
  const { app, safeStorage } = require('electron')
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-r4-live-'))
  const isolatedProfile = path.join(data, 'electron')
  // Reuse ONLY the DPAPI-wrapped encryption context of the credential's
  // original profile, not its cookies, sessions, cache, or browsing data.
  const sourceState = path.join(app.getPath('appData'), 'ModAgent-TestProfiles/shared-credentials-20260906-r3/subscription/user-data/Local State')
  const state = JSON.parse(fs.readFileSync(sourceState, 'utf8'))
  if (!state.os_crypt?.encrypted_key) throw Error('Original credential encryption context unavailable')
  fs.mkdirSync(isolatedProfile, { recursive: true })
  fs.writeFileSync(path.join(isolatedProfile, 'Local State'), JSON.stringify({ os_crypt: { encrypted_key: state.os_crypt.encrypted_key } }))
  app.setPath('userData', isolatedProfile)
  app.whenReady().then(() => {
    if (!safeStorage.isEncryptionAvailable()) throw Error('Windows encryption unavailable')
    const appData = app.getPath('appData')
    const shared = path.join(appData, 'ModAgent/Credentials/credentials-v2.json')
    const profiles = ['free', 'subscription'].map(edition => path.join(appData, 'ModAgent-TestProfiles/shared-credentials-20260906-r3', edition, 'data/credentials-v2.json'))
    let record
    for (const file of [...profiles, shared]) {
      if (!fs.existsSync(file)) continue
      let stage = 'envelope'
      try {
        const envelope = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''))
        stage = 'decrypt'
        const decrypted = safeStorage.decryptString(Buffer.from(envelope.encrypted, 'base64'))
        stage = 'decode'
        const value = JSON.parse(decrypted)
        stage = 'route'
        const route = new URL(value.llm_endpoint)
        console.log(JSON.stringify({ credential_route_host: route.hostname, model: value.llm_model, key_present: !!value.llm_api_key }))
        if (route.protocol === 'https:' && route.hostname === 'api.deepseek.com' && value.llm_api_key && value.llm_model) { record = value; break }
      } catch (_) { console.log('Credential unavailable at stage: ' + stage + '; no secret data logged') }
    }
    if (!record) {
      for (const dir of [path.join(os.homedir(), '.modagent'), path.join(os.homedir(), '.modagent-beta')]) {
        try {
          const config = JSON.parse(fs.readFileSync(path.join(dir, 'config.json'), 'utf8').replace(/^\uFEFF/, ''))
          const envelope = JSON.parse(fs.readFileSync(path.join(dir, 'secrets.json'), 'utf8').replace(/^\uFEFF/, ''))
          const route = new URL(config.llm_endpoint)
          if (route.hostname !== 'api.deepseek.com' || route.protocol !== 'https:') continue
          const key = safeStorage.decryptString(Buffer.from(envelope.values.llm_api_key, 'base64'))
          if (key && config.llm_model) { record = { llm_api_key: key, llm_endpoint: config.llm_endpoint, llm_model: config.llm_model }; break }
        } catch (_) { /* The legacy profile also remains read-only. */ }
      }
    }
    if (!record) throw Error('No readable DeepSeek credential route found; no API calls made')
    const repo = path.resolve(__dirname, '../..')
    const child = spawn('python', [path.join(repo, 'scripts/eval_r4_live.py')], { cwd: repo, windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONPATH: repo, MODAGENT_DATA_DIR: path.join(data, 'data'),
        MODAGENT_LLM_API_KEY: record.llm_api_key, MODAGENT_LLM_ENDPOINT: record.llm_endpoint, MODAGENT_LLM_MODEL: record.llm_model,
        MODAGENT_NEXUS_API_KEY: '', MODAGENT_TAVILY_API_KEY: '', MODAGENT_SECURE_SECRETS: '1', MODAGENT_CREDENTIAL_ROUTE: '1' },
    })
    child.stdout.on('data', chunk => process.stdout.write(chunk))
    child.stderr.on('data', () => {}) // Exception types/results are captured in the sanitized report.
    child.on('error', () => { console.error('Could not start isolated evaluator'); app.exit(1) })
    child.on('exit', code => app.exit(code || 0))
  }).catch(error => { console.error(error.message); app.exit(1) })
}
