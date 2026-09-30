const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { createCredentialBroker } = require('../credentialBroker');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-r6-boundaries-'));
const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: value => Buffer.from('fake-local:' + value),
  decryptString: bytes => {
    const value = bytes.toString();
    if (!value.startsWith('fake-local:')) throw Error('foreign-profile');
    return value.slice(11);
  },
};
const fake = { llm_api_key: 'NOT-A-REAL-KEY', llm_endpoint: 'https://example.invalid/v1', llm_model: 'fake' };
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
let checks = 0;
function check(fn) { fn(); checks++; }
function make(name) {
  const dataDir = path.join(root, name, 'local');
  const sharedDir = path.join(root, name, 'shared');
  const create = () => createCredentialBroker({ dataDir, sharedDir, localOnly: true, safeStorage });
  return { dataDir, sharedDir, create, local: path.join(dataDir, 'credentials-v2.json'), shared: path.join(sharedDir, 'credentials-v2.json') };
}
function corrupt(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ version: 2, encrypted: Buffer.from('foreign-fake-data').toString('base64') }));
}
// A foreign shared vault cannot block first setup, later save, or a new broker.
const first = make('foreign'); corrupt(first.shared);
const original = hash(first.shared);
const broker = first.create();
check(() => assert.deepEqual(broker.load(), {}));
check(() => assert.equal(broker.save(fake).llm_model, 'fake'));
check(() => assert.equal(first.create().load().llm_api_key, fake.llm_api_key));
check(() => assert.equal(broker.save({ llm_model: 'fake-next' }).llm_model, 'fake-next'));
check(() => assert.equal(first.create().load().llm_model, 'fake-next'));
check(() => assert.equal(hash(first.shared), original));
check(() => assert(!JSON.stringify(broker.status()).includes(fake.llm_api_key)));
// A local vault failure is different: never overwrite it or claim success.
const broken = make('broken-local'); corrupt(broken.local);
const before = hash(broken.local);
check(() => assert.throws(() => broken.create().save(fake), /credential_store_unreadable/));
check(() => assert.equal(hash(broken.local), before));
check(() => assert(!fs.existsSync(broken.shared)));
// Publishing a default is optional, even when another writer holds its lock.
const locked = make('locked-shared'); fs.mkdirSync(locked.sharedDir, { recursive: true });
fs.writeFileSync(locked.shared + '.lock', 'fixture lock');
const waiting = locked.create();
check(() => assert.equal(waiting.save(fake).llm_model, 'fake'));
check(() => assert.equal(waiting.status().shared_warning, 'credential_shared_unavailable'));
check(() => assert.equal(locked.create().load().llm_api_key, fake.llm_api_key));
// Failed encryption of a local update preserves the prior committed vault.
const stable = make('encryption-fails'); const stableBroker = stable.create(); stableBroker.save(fake);
const stableHash = hash(stable.local);
const failing = createCredentialBroker({ dataDir: stable.dataDir, sharedDir: stable.sharedDir, localOnly: true,
  safeStorage: { ...safeStorage, encryptString: () => { throw Error('cipher unavailable'); } } });
check(() => assert.throws(() => failing.save({ ...fake, llm_model: 'not-saved' })));
check(() => assert.equal(hash(stable.local), stableHash));
check(() => assert.equal(stable.create().load().llm_model, 'fake'));
console.log(`R6 credential boundaries: ${checks} checks passed; fake fixtures retained in temp.`);
