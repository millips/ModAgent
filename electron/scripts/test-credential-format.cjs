const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createCredentialBroker } = require('../credentialBroker');
// Isolated fake cipher, never reads the real vault.
const safeStorage = { isEncryptionAvailable: () => true,
  encryptString: text => Buffer.from(text), decryptString: data => data.toString() };
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modagent-format-'));
(async () => {
  const { saveCredentialSettings, credentialErrorMessage } = await import('../src/credentialSettings.mjs');
  const sharedDir = path.join(root, 'shared');
  const dataDir = path.join(root, 'profile');
  const options = { sharedDir, dataDir, safeStorage, localOnly: true };
  const broker = createCredentialBroker(options);
  broker.load();
  const route = { llm_endpoint: 'https://example.invalid/v1', llm_model: 'fake' };
  broker.save({ ...route, llm_api_key: 'valid-fake-key' });
  const files = [dataDir, sharedDir].map(dir => path.join(dir, 'credentials-v2.json'));
  const prior = files.map(file => fs.readFileSync(file, 'utf8'));
  for (const field of ['llm_api_key', 'nexus_api_key', 'tavily_api_key']) {
    for (const value of ['中文占位密钥', 'fake\nkey', 'fake key', 'fake\x00key', 'fake\x7fkey']) {
      const code = `credential_${field}_invalid`;
      assert.throws(() => broker.save({ [field]: value }), { message: code });
      assert.deepEqual(files.map(file => fs.readFileSync(file, 'utf8')), prior);
      for (const store of [undefined, async () => assert.fail('must not call broker')]) {
        await assert.rejects(saveCredentialSettings({ [field]: value }, store), { message: code });
      }
      assert.match(credentialErrorMessage(new Error(code), 'zh-CN'), /格式/);
      assert.match(credentialErrorMessage(new Error(code), 'en'), /format/);
    }
  }
  // Old malformed values can still be loaded and corrected via Settings.
  const legacy = { ...route, llm_api_key: '中文占位密钥' };
  fs.writeFileSync(files[0], JSON.stringify({ version: 2, encrypted: Buffer.from(JSON.stringify(legacy)).toString('base64') }));
  const restored = createCredentialBroker(options);
  assert.equal(restored.load().llm_api_key, legacy.llm_api_key);
  assert.equal(restored.save({ llm_api_key: ' local-token ' }).llm_api_key, 'local-token');
  console.log('Credential format: invalid saves preserved both vaults; legacy correction passed');
})().catch(error => { console.error(error); process.exitCode = 1; })
  .finally(() => fs.rmSync(root, { recursive: true, force: true }));
