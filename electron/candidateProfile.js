const path = require('path');

function candidateId(packageInfo = {}) {
  const value = packageInfo.modagentCandidateId;
  if (!value) return '';
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9-]{2,63}$/.test(value)) {
    throw new Error('Invalid isolated test candidate identity');
  }
  return value;
}

function candidateProfile(packageInfo, edition, appData, env = {}, smoke = false) {
  const id = candidateId(packageInfo);
  if (!id) return null;
  if (!['free', 'subscription'].includes(edition)) throw new Error('Invalid test edition');
  const root = path.join(appData, 'ModAgent-TestProfiles', id, edition);
  // Ordinary test launches must not inherit a production MODAGENT_DATA_DIR.
  // Only the explicit packaged smoke path may use temporary harness folders.
  return {
    id,
    dataDir: path.resolve(smoke && env.MODAGENT_DATA_DIR || path.join(root, 'data')),
    userDataDir: path.resolve(smoke && env.MODAGENT_USER_DATA_DIR || path.join(root, 'user-data')),
    coreMode: 'on',
  };
}

module.exports = { candidateId, candidateProfile };
