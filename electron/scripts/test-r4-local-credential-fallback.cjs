// Regression originally failing in r4/r5. Fake secrets only, no application profiles.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createCredentialBroker } = require('../credentialBroker');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-r4-credential-fallback-'));
const dataDir = path.join(root, 'local');
const sharedDir = path.join(root, 'shared');
const fakeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: value => Buffer.from('profile-b:' + value),
  decryptString: value => {
    const text = value.toString();
    if (!text.startsWith('profile-b:')) throw Error('different_profile');
    return text.slice('profile-b:'.length);
  },
};
const fakeRecord = {
  llm_api_key: 'FAKE-NOT-A-REAL-KEY',
  llm_endpoint: 'https://example.invalid/v1',
  llm_model: 'fake-model',
};
function writeEnvelope(directory, bytes) {
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'credentials-v2.json'),
    JSON.stringify({ version: 2, encrypted: bytes.toString('base64') }));
}
writeEnvelope(dataDir, fakeStorage.encryptString(JSON.stringify(fakeRecord)));
const create = () => createCredentialBroker({ dataDir, sharedDir, localOnly: true, safeStorage: fakeStorage });
assert.equal(create().load().llm_model, 'fake-model');
console.log('PASS: valid local credentials load when no shared envelope exists');
writeEnvelope(sharedDir, Buffer.from('profile-a:fake-encrypted-record'));
const sharedBefore = fs.readFileSync(path.join(sharedDir, 'credentials-v2.json'));
try {
  assert.equal(create().load().llm_model, 'fake-model');
  assert.deepEqual(fs.readFileSync(path.join(sharedDir, 'credentials-v2.json')), sharedBefore);
  console.log('PASS: unreadable shared envelope does not disable valid local credentials');
} catch (error) {
  console.error('FAIL: unreadable shared envelope prevents valid local credentials from loading (' + error.message + ')');
  process.exitCode = 1;
}
