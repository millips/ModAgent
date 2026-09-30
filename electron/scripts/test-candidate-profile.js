const assert = require('node:assert/strict');
const path = require('node:path');
const { candidateId, candidateProfile } = require('../candidateProfile');
const { getAppIdentity } = require('../appIdentity');

delete process.env.MODAGENT_EDITION;
delete process.env.MODAGENT_CHANNEL;
const pkg = { version: '1.6.0-beta.1', modagentEdition: 'free', modagentChannel: 'beta', modagentCandidateId: 'core-safety-20260906-r1' };
const productionEnv = { MODAGENT_DATA_DIR: 'C:/production-data', MODAGENT_USER_DATA_DIR: 'C:/production-ui' };
assert.equal(candidateProfile({}, 'free', 'C:/appdata'), null);
for (const value of ['../production', 'a/b', 'x\\y', '.', '']) {
  if (!value) assert.equal(candidateId({ modagentCandidateId: value }), '');
  else assert.throws(() => candidateId({ modagentCandidateId: value }));
}
const profile = candidateProfile(pkg, 'free', 'C:/appdata', productionEnv);
assert.equal(profile.dataDir, path.resolve('C:/appdata/ModAgent-TestProfiles/core-safety-20260906-r1/free/data'));
assert.notEqual(profile.userDataDir, path.resolve(productionEnv.MODAGENT_USER_DATA_DIR));
assert.equal(profile.coreMode, 'on');
const pProfile = candidateProfile(pkg, 'subscription', 'C:/appdata', productionEnv);
assert.notEqual(profile.dataDir, pProfile.dataDir);
const smoke = candidateProfile(pkg, 'free', 'C:/appdata', { MODAGENT_DATA_DIR: 'C:/temporary-smoke' }, true);
assert.equal(smoke.dataDir, path.resolve('C:/temporary-smoke'));
const identity = getAppIdentity(pkg);
assert.match(identity.productName, /Core Safety Test/);
assert.match(identity.appId, /test.core-safety-20260906-r1$/);
assert.equal(identity.manualUpdateManifestUrl, '');
process.env.MODAGENT_EDITION = 'subscription';
process.env.MODAGENT_CHANNEL = 'stable';
assert.equal(getAppIdentity(pkg).edition, 'free', 'inherited production env cannot change the test edition');
assert.equal(getAppIdentity(pkg).channel, 'beta');
assert.throws(() => getAppIdentity({ ...pkg, modagentChannel: 'stable' }));
console.log('ISOLATED CANDIDATE PROFILE TESTS PASSED');
