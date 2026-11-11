const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { createCredentialBroker, credentialOptions, endpointId } = require('../credentialBroker');

// Fake cipher only for isolated fixtures. Production always injects safeStorage.
const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: text => Buffer.from([...Buffer.from(text)].map(n => n ^ 0x51)),
  decryptString: data => Buffer.from([...data].map(n => n ^ 0x51)).toString(),
};
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-credentials-test-'));
let assertions = 0;
function check(test) { test(); assertions++; }
function json(file, data) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(data)); }
function hash(file) { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
function broker(name, extra = {}) {
  return createCredentialBroker({ dataDir: path.join(root, name), sharedDir: path.join(root, 'shared'),
    legacyDirs: [path.join(root, 'old')], localOnly: true, safeStorage, ...extra });
}
const route = { llm_endpoint: 'https://provider.example/v1', llm_model: 'test-model' };
try {
  json(path.join(root, 'old', 'config.json'), { ...route, game_root: 'DO-NOT-COPY', llm_api_key: 'plaintext-obsolete' });
  json(path.join(root, 'old', 'secrets.json'), { version: 1, values: {
    llm_api_key: safeStorage.encryptString('fake-llm').toString('base64'),
    nexus_api_key: safeStorage.encryptString('fake-nexus').toString('base64'),
  } });
  const originals = ['config.json', 'secrets.json'].map(n => hash(path.join(root, 'old', n)));
  const first = broker('r3');
  check(() => assert.deepEqual(first.load(), { ...route, llm_api_key: 'fake-llm', nexus_api_key: 'fake-nexus' }));
  check(() => assert.deepEqual(['config.json', 'secrets.json'].map(n => hash(path.join(root, 'old', n))), originals));
  check(() => assert.equal(fs.existsSync(path.join(root, 'r3', 'config.json')), false));
  const vaultFile = path.join(root, 'shared', 'credentials-v2.json');
  check(() => assert(!fs.readFileSync(vaultFile, 'utf8').includes('fake-llm')));
  check(() => assert(!JSON.stringify(first.status()).includes('fake-')));
  check(() => assert.equal(first.status().origin, 'shared'));
  const sharedHash = hash(vaultFile);
  first.save({ ...route, llm_api_key: 'test-only-key' });
  check(() => assert.equal(hash(vaultFile), sharedHash));
  check(() => assert.equal(broker('r3').load().llm_api_key, 'test-only-key'));
  check(() => assert.equal(broker('r4').load().llm_api_key, 'fake-llm'));
  check(() => assert.throws(() => first.save({ ...route, llm_endpoint: 'https://other.example/v1' }), /requires_key/));
  check(() => assert.equal(broker('r3').load().llm_api_key, 'test-only-key'));
  first.save({ ...route, llm_endpoint: 'https://other.example/v1', llm_api_key: 'other-provider-key' });
  check(() => assert.equal(broker('r3').load().llm_endpoint, 'https://other.example/v1'));
  first.save({ llm_api_key: '' });
  check(() => assert.equal(broker('r3').load().llm_api_key, '', 'deleted local key does not inherit shared again'));
  json(path.join(root, 'existing', 'config.json'), { llm_endpoint: 'https://unrelated.example/v1', llm_model: 'local' });
  check(() => assert.equal(broker('existing').load().llm_api_key, ''));
  const env = { MODAGENT_LLM_API_KEY: 'stale-key' };
  first.applyToEnvironment({}, env);
  check(() => assert.equal(env.MODAGENT_LLM_API_KEY, ''));
  check(() => assert.equal(env.MODAGENT_CREDENTIAL_ROUTE, '1'));
  const p = broker('production', { localOnly: false }); p.load();
  const p2 = broker('production2', { localOnly: false }); p2.load();
  p.save({ ...route, nexus_api_key: 'updated-nexus' });
  p2.save({ ...route, tavily_api_key: 'updated-tavily' });
  check(() => assert.equal(broker('r5').load().nexus_api_key, 'updated-nexus', 'concurrent profiles retain unrelated edits'));
  check(() => assert.equal(broker('r5').load().tavily_api_key, 'updated-tavily'));
  const locked = `${vaultFile}.lock`; fs.writeFileSync(locked, '');
  check(() => assert.throws(() => p.save(route), /busy/)); fs.unlinkSync(locked);
  check(() => assert.throws(() => broker('crypto-off', { safeStorage: { isEncryptionAvailable: () => false } }).load(), /unavailable/));
  const corrupt = path.join(root, 'broken'); json(path.join(corrupt, 'credentials-v2.json'), { version: 999 });
  const broken = broker('broken-local', { sharedDir: corrupt });
  check(() => assert.deepEqual(broken.load(), {}));
  check(() => assert.equal(broken.save({ ...route, llm_api_key: 'replacement' }).llm_api_key, 'replacement'));
  check(() => assert.equal(broken.status().shared_warning, 'credential_shared_unavailable'));
  check(() => assert.equal(broker('broken-local', { sharedDir: corrupt }).load().llm_api_key, 'replacement'));
  const sharedWriter = broker('broken-production', { sharedDir: corrupt, localOnly: false });
  check(() => assert.throws(() => sharedWriter.save({ ...route, llm_api_key: 'no-overwrite' }), /unreadable/));
  check(() => assert.equal(JSON.parse(fs.readFileSync(path.join(corrupt, 'credentials-v2.json'))).version, 999));
  const blankShared = path.join(root, 'new-account');
  const newTest = broker('new-test', { sharedDir: blankShared, legacyDirs: [] }); newTest.load();
  newTest.save({ ...route, llm_api_key: 'first-setup' });
  check(() => assert.equal(broker('future-test', { sharedDir: blankShared, legacyDirs: [] }).load().llm_api_key, 'first-setup'));
  const partialShared = path.join(root, 'partial-account');
  const partial = broker('partial-test', { sharedDir: partialShared, legacyDirs: [] });
  partial.load(); partial.save({ ...route, llm_api_key: 'first', nexus_api_key: 'first-nexus' });
  partial.save({ tavily_api_key: 'first-tavily' });
  check(() => assert.equal(broker('partial-future', { sharedDir: partialShared, legacyDirs: [] }).load().tavily_api_key, undefined, 'later test-only additions do not change the shared default'));
  const unknownRoot = path.join(root, 'unknown-account');
  json(path.join(root, 'unbound', 'config.json'), { llm_api_key: 'no-route' });
  check(() => assert.equal(broker('no-route-test', { sharedDir: unknownRoot, legacyDirs: [path.join(root, 'unbound')] }).load().llm_api_key, undefined));
  const options = credentialOptions({ dataDir: root, appData: 'REAL-APPDATA', homeDir: 'REAL-HOME', candidate: true, smoke: true });
  check(() => assert.deepEqual(options.legacyDirs, []));
  check(() => assert(options.sharedDir.startsWith(root)));
  check(() => assert.equal(endpointId('https://PROVIDER.example/v1/'), route.llm_endpoint));
  for (const url of ['https://user:pass@example.com', 'https://example.com?key=x', 'file:///secrets', 'https://example.com/#key']) {
    check(() => assert.throws(() => endpointId(url)));
  }
  console.log(`Credential broker: ${assertions} checks passed (fake credentials only)`);
} finally { fs.rmSync(root, { recursive: true, force: true }); }
