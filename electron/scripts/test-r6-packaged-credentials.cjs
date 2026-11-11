// Real Electron encryption in unrelated profiles; only fake credentials.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

if (process.versions.electron) {
  const { app, safeStorage } = require('electron');
  const [file, profile] = process.argv.slice(2);
  app.setPath('userData', profile);
  app.whenReady().then(() => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ version: 2, encrypted: safeStorage.encryptString(JSON.stringify({
      llm_api_key: 'foreign-profile-fake-key', llm_endpoint: 'https://foreign.invalid/v1', llm_model: 'fake',
    })).toString('base64') }), { flag: 'wx' });
    app.exit(0);
  }).catch(() => app.exit(1));
} else {
  const [edition, executableArg, outputDir] = process.argv.slice(2);
  assert(['free', 'subscription'].includes(edition));
  const executable = path.resolve(executableArg);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-r6-save-'));
  const data = path.join(root, 'data');
  const shared = path.join(data, 'smoke-credentials/credentials-v2.json');
  const local = path.join(data, 'credentials-v2.json');
  const seeded = spawnSync(require('electron'), [__filename, shared, path.join(root, 'foreign-profile')],
    { windowsHide: true, encoding: 'utf8', timeout: 20000 });
  assert.equal(seeded.status, 0, 'create foreign-context fake ciphertext');
  const sharedHash = digest(shared);
  const env = { ...process.env, MODAGENT_DATA_DIR: data, MODAGENT_USER_DATA_DIR: path.join(root, 'local-profile') };
  for (let run = 0; run < 2; run++) {
    const result = spawnSync(executable, ['--smoke-test', '--smoke-credential-setup'],
      { windowsHide: true, encoding: 'utf8', timeout: 60000, env });
    assert.equal(result.status, 0, `setup/restart ${run} failed; fixture retained: ${root}`);
    assert.equal(digest(shared), sharedHash, 'foreign shared file must not change');
    const encrypted = fs.readFileSync(local, 'utf8');
    assert(!encrypted.includes('credential-setup-fake-key'), 'local key is encrypted');
    const log = fs.readFileSync(path.join(data, 'editions', edition, 'logs/desktop.log'), 'utf8');
    assert(log.includes('Credential setup fallback smoke passed'));
    assert(!log.includes('credential-setup-fake-key') && !log.includes('foreign-profile-fake-key'));
  }
  const report = { edition, passed: true, fake_credentials_only: true, model_calls: 0,
    foreign_profile_encryption: true, actual_setup_controls: true, actual_save_ipc: true,
    restart_local_reuse: true, shared_unchanged: true, fixture: root };
  const output = path.join(outputDir ? path.resolve(outputDir) : path.resolve(__dirname, '../../build/credential-save-r6'), `credential-setup-${edition}.json`);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}
