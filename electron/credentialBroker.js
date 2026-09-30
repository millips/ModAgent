// Only credentials and their LLM route cross profile boundaries. Never import
// game paths, inventory, licenses, conversations, or task confirmations here.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const KEYS = ['llm_api_key', 'nexus_api_key', 'tavily_api_key'];
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
function endpointId(value) {
  const url = new URL(String(value || '').trim());
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('credential_endpoint_invalid');
  }
  return url.toString().replace(/\/+$/, '');
}
function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
}
function credentialOptions({ dataDir, appData, homeDir, candidate, smoke }) {
  return {
    dataDir,
    sharedDir: smoke ? path.join(dataDir, 'smoke-credentials') : path.join(appData, 'ModAgent', 'Credentials'),
    legacyDirs: smoke ? [] : [path.join(homeDir, '.modagent'), path.join(homeDir, '.modagent-beta')],
    localOnly: Boolean(candidate || smoke),
  };
}
function createCredentialBroker({ dataDir, sharedDir, legacyDirs = [], localOnly = false, safeStorage }) {
  const localFile = path.join(dataDir, 'credentials-v2.json');
  const sharedFile = path.join(sharedDir, 'credentials-v2.json');
  let active = {};
  let origin = 'none';
  let sharedWarning = '';
  function ready() {
    if (!safeStorage.isEncryptionAvailable()) throw new Error('credential_encryption_unavailable');
  }
  function validate(record) {
    if (!record || typeof record !== 'object' || Array.isArray(record)) throw new Error('credential_store_invalid');
    for (const key of KEYS) if (own(record, key) && typeof record[key] !== 'string') throw new Error('credential_store_invalid');
    if (record.llm_api_key) {
      record.llm_endpoint = endpointId(record.llm_endpoint);
      if (typeof record.llm_model !== 'string' || !record.llm_model.trim()) throw new Error('credential_model_missing');
    }
    // Whitelist rather than trusting arbitrary decrypted JSON fields.
    return Object.fromEntries([...KEYS, 'llm_endpoint', 'llm_model'].filter(k => own(record, k)).map(k => [k, record[k]]));
  }
  function read(file) {
    if (!fs.existsSync(file)) return null;
    ready();
    try {
      const envelope = readJson(file);
      if (envelope.version !== 2 || typeof envelope.encrypted !== 'string') throw new Error();
      return validate(JSON.parse(safeStorage.decryptString(Buffer.from(envelope.encrypted, 'base64'))));
    } catch (_) { throw new Error('credential_store_unreadable'); }
  }
  function write(file, value, onlyIfAbsent = false) {
    ready();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const lock = `${file}.lock`;
    let descriptor;
    try { descriptor = fs.openSync(lock, 'wx', 0o600); }
    catch (_) { throw new Error('credential_store_busy'); }
    const temp = `${file}.${crypto.randomUUID()}.tmp`;
    try {
      // Do not overwrite corrupt/newer stores; never treat a read failure as empty.
      const existing = read(file);
      if (onlyIfAbsent && existing) return existing;
      const clean = validate({ ...(typeof value === 'function' ? value(existing) : value) });
      const encrypted = safeStorage.encryptString(JSON.stringify(clean)).toString('base64');
      fs.writeFileSync(temp, JSON.stringify({ version: 2, encrypted }), { flag: 'wx', mode: 0o600 });
      fs.renameSync(temp, file);
      return clean;
    } finally {
      if (fs.existsSync(temp)) fs.unlinkSync(temp);
      fs.closeSync(descriptor);
      fs.unlinkSync(lock);
    }
  }
  function legacy(dir) {
    // Read-only import. The original secrets/config files are never modified.
    const configFile = path.join(dir, 'config.json');
    const secretsFile = path.join(dir, 'secrets.json');
    try {
      const config = fs.existsSync(configFile) ? readJson(configFile) : {};
      const envelope = fs.existsSync(secretsFile) ? readJson(secretsFile) : { values: {} };
      const result = {};
      for (const key of KEYS) {
        if (envelope.values?.[key]) result[key] = safeStorage.decryptString(Buffer.from(envelope.values[key], 'base64'));
        else if (typeof config[key] === 'string' && config[key]) result[key] = config[key];
      }
      if (result.llm_api_key) {
        // A key without an explicit route is NOT attached to a guessed provider.
        if (!config.llm_endpoint || !config.llm_model) delete result.llm_api_key;
        else {
          result.llm_endpoint = endpointId(config.llm_endpoint);
          result.llm_model = config.llm_model;
        }
      }
      return validate(result);
    } catch (_) { return {}; }
  }
  function load() {
    ready();
    sharedWarning = '';
    let shared = null;
    try { shared = read(sharedFile); }
    catch (error) {
      // An optional shared default must not disable this profile's own vault.
      // Production/shared writes remain fail-closed; never erase the old store.
      if (!localOnly) throw error;
      sharedWarning = 'credential_shared_unavailable';
    }
    if (!shared && !sharedWarning) {
      const imported = {};
      for (const dir of [...legacyDirs, dataDir]) {
        const source = legacy(dir);
        if (!imported.llm_api_key && source.llm_api_key) {
          for (const k of ['llm_api_key', 'llm_endpoint', 'llm_model']) imported[k] = source[k];
        }
        for (const k of ['nexus_api_key', 'tavily_api_key']) if (!imported[k] && source[k]) imported[k] = source[k];
      }
      if (KEYS.some(k => imported[k])) {
        try { shared = write(sharedFile, imported, true); }
        catch (error) {
          if (!localOnly) throw error;
          sharedWarning = 'credential_shared_unavailable';
          // Imported values can still be used locally; publishing is optional.
          shared = imported;
        }
      }
    }
    const local = read(localFile);
    const prior = local || (localOnly ? legacy(dataDir) : {});
    active = { ...(shared || {}), ...prior };
    origin = local ? 'local' : KEYS.some(k => prior[k]) ? 'legacy-local' : shared ? 'shared' : 'none';
    // Respect an existing profile's explicitly selected endpoint. On a fresh
    // profile there is no config, so inherit key + endpoint + model as a unit.
    const configFile = path.join(dataDir, 'config.json');
    if (!local && fs.existsSync(configFile)) {
      const config = readJson(configFile);
      if (config.llm_endpoint) {
        const endpoint = endpointId(config.llm_endpoint);
        if (active.llm_endpoint !== endpoint) active.llm_api_key = '';
        active.llm_endpoint = endpoint;
        active.llm_model = config.llm_model || active.llm_model || '';
      }
    }
    return { ...active };
  }
  function save(updates) {
    ready();
    // Validate only explicit edits. Legacy malformed secrets remain readable so
    // the user can correct them; a rejected edit never replaces either vault.
    for (const key of KEYS) {
      if (own(updates, key) && /[^\x21-\x7e]/.test(String(updates[key] || '').trim())) {
        throw new Error(`credential_${key}_invalid`);
      }
    }
    // Candidates always save an override, never replace the common default.
    // Read-modify-write under the lock avoids losing another process's edits.
    active = write(localOnly ? localFile : sharedFile, existing => {
      const next = { ...active, ...(existing || {}) };
      const endpoint = endpointId(updates.llm_endpoint || next.llm_endpoint);
      if (endpoint !== next.llm_endpoint && !updates.llm_api_key) throw new Error('credential_endpoint_requires_key');
      next.llm_endpoint = endpoint;
      next.llm_model = String(updates.llm_model || next.llm_model || '').trim();
      for (const key of KEYS) if (own(updates, key)) next[key] = String(updates[key] || '').trim();
      return next;
    });
    // On a brand-new account even first setup in a test build is reusable.
    // Once a shared default exists, test edits can never replace it.
    if (localOnly) {
      try {
        if (!read(sharedFile)) write(sharedFile, active, true);
        sharedWarning = '';
      } catch (_) {
        // The mandatory local write has committed. Failure to publish a shared
        // default is a warning, not a failed local save or a rollback claim.
        sharedWarning = 'credential_shared_unavailable';
      }
    }
    origin = localOnly ? 'local' : 'shared';
    return { ...active };
  }
  function applyToEnvironment(value, env = process.env) {
    for (const key of [...KEYS, 'llm_endpoint', 'llm_model']) {
      env[`MODAGENT_${key.toUpperCase()}`] = value[key] || '';
    }
    env.MODAGENT_SECURE_SECRETS = '1';
    env.MODAGENT_CREDENTIAL_ROUTE = '1';
  }
  function status() {
    return { origin, localOnly, shared_warning: sharedWarning, llm_set: Boolean(active.llm_api_key), api_key_set: Boolean(active.nexus_api_key), tavily_set: Boolean(active.tavily_api_key) };
  }
  return { load, save, applyToEnvironment, status };
}
module.exports = { createCredentialBroker, credentialOptions, endpointId };
