const fs = require('fs');
const path = require('path');
const { safeStorage } = require('electron');

const SECRET_MAP = {
  nexus_api_key: 'MODAGENT_NEXUS_API_KEY',
  llm_api_key: 'MODAGENT_LLM_API_KEY',
  tavily_api_key: 'MODAGENT_TAVILY_API_KEY',
};

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(value, null, 2), 'utf8');
  fs.renameSync(tempPath, filePath);
}

function createSecurityStore(dataDir, logger = console) {
  const secretsFile = path.join(dataDir, 'secrets.json');
  const configFile = path.join(dataDir, 'config.json');

  function encryptionReady() {
    return safeStorage.isEncryptionAvailable();
  }

  function readEnvelope() {
    if (!fs.existsSync(secretsFile)) return { version: 1, values: {} };
    try {
      const parsed = JSON.parse(fs.readFileSync(secretsFile, 'utf8').replace(/^\uFEFF/, ''));
      return { version: 1, values: parsed.values || {} };
    } catch (error) {
      logger.error('Unable to read encrypted secrets:', error.message);
      return { version: 1, values: {} };
    }
  }

  function load() {
    if (!encryptionReady()) return {};
    const envelope = readEnvelope();
    const result = {};
    for (const key of Object.keys(SECRET_MAP)) {
      const encoded = envelope.values[key];
      if (!encoded) continue;
      try {
        result[key] = safeStorage.decryptString(Buffer.from(encoded, 'base64'));
      } catch (error) {
        logger.error(`Unable to decrypt ${key}:`, error.message);
      }
    }
    return result;
  }

  function save(updates) {
    if (!encryptionReady()) throw new Error('Windows secure storage is unavailable');
    const envelope = readEnvelope();
    for (const key of Object.keys(SECRET_MAP)) {
      if (!Object.prototype.hasOwnProperty.call(updates, key)) continue;
      const value = String(updates[key] || '');
      if (value) {
        envelope.values[key] = safeStorage.encryptString(value).toString('base64');
      } else {
        delete envelope.values[key];
      }
    }
    atomicWriteJson(secretsFile, envelope);
    return load();
  }

  function migratePlaintextConfig() {
    if (!encryptionReady() || !fs.existsSync(configFile)) return load();
    let config;
    try {
      config = JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^\uFEFF/, ''));
    } catch (error) {
      logger.error('Unable to inspect config for secret migration:', error.message);
      return load();
    }
    const encrypted = load();
    const updates = {};
    let changed = false;
    for (const key of Object.keys(SECRET_MAP)) {
      const plaintext = String(config[key] || '');
      if (plaintext && !encrypted[key]) updates[key] = plaintext;
      if (Object.prototype.hasOwnProperty.call(config, key)) {
        delete config[key];
        changed = true;
      }
    }
    const merged = Object.keys(updates).length ? save(updates) : encrypted;
    if (changed) {
      atomicWriteJson(configFile, config);
      logger.info('Migrated API keys out of plaintext config.json');
    }
    return merged;
  }

  function applyToEnvironment(secrets, env = process.env) {
    for (const [key, envName] of Object.entries(SECRET_MAP)) {
      if (secrets[key]) env[envName] = secrets[key];
      else delete env[envName];
    }
    env.MODAGENT_SECURE_SECRETS = '1';
  }

  return { load, save, migratePlaintextConfig, applyToEnvironment, secretsFile };
}

module.exports = { createSecurityStore, SECRET_MAP };
