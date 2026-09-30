const path = require('path');
const { candidateId } = require('./candidateProfile');

const IDENTITIES = {
  free: {
    edition: 'free',
    productName: 'ModAgent',
    executableName: 'ModAgent',
    appId: 'com.modagent.desktop.free',
    userDataFolder: 'ModAgent',
    iconName: 'modagent-free.ico',
    artifactPrefix: 'ModAgent',
    updateChannel: 'free',
    manualUpdateManifestUrl: 'https://github.com/millips/ModAgent/releases/latest/download/free-update.json',
  },
  subscription: {
    edition: 'subscription',
    productName: 'ModAgent P',
    executableName: 'ModAgentP',
    appId: 'com.modagent.desktop.pro',
    userDataFolder: 'ModAgent P',
    iconName: 'modagent-p.ico',
    artifactPrefix: 'ModAgent-P',
    updateChannel: 'subscription',
    manualUpdateManifestUrl: 'https://github.com/millips/ModAgent/releases/latest/download/p-update.json',
  },
};

function getAppIdentity(packageInfo = {}) {
  const testId = candidateId(packageInfo);
  const requested = testId ? packageInfo.modagentEdition : process.env.MODAGENT_EDITION || packageInfo.modagentEdition;
  const edition = requested === 'subscription' ? 'subscription' : 'free';
  const requestedChannel = testId ? packageInfo.modagentChannel : process.env.MODAGENT_CHANNEL || packageInfo.modagentChannel;
  const channel = requestedChannel === 'beta' ? 'beta' : 'stable';
  const base = IDENTITIES[edition];
  if (testId && channel !== 'beta') throw new Error('Test candidates must use the beta channel');
  const identity = channel === 'beta'
    ? {
        ...base,
        productName: `${base.productName} Beta`,
        executableName: `${base.executableName}Beta`,
        appId: `${base.appId}.beta`,
        userDataFolder: `${base.userDataFolder} Beta`,
        artifactPrefix: `${base.artifactPrefix}-Beta`,
        updateChannel: `${base.updateChannel}-beta`,
      }
    : base;
  return {
    ...identity,
    ...(testId ? {
      productName: `${identity.productName} Core Safety Test (${testId})`,
      executableName: `${identity.executableName}-CoreSafety`,
      appId: `${identity.appId}.test.${testId}`,
      userDataFolder: `${identity.userDataFolder} Test ${testId}`,
      manualUpdateManifestUrl: '',
      candidateId: testId,
    } : {}),
    channel,
    isBeta: channel === 'beta',
    version: packageInfo.version || '0.0.0',
    iconPath: path.join(__dirname, 'assets', 'icons', identity.iconName),
  };
}

module.exports = { IDENTITIES, getAppIdentity };
