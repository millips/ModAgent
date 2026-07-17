const path = require('path');

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
  },
  subscription: {
    edition: 'subscription',
    productName: 'ModAgent Pro',
    executableName: 'ModAgentPro',
    appId: 'com.modagent.desktop.pro',
    userDataFolder: 'ModAgent Pro',
    iconName: 'modagent-subscription.ico',
    artifactPrefix: 'ModAgent-Pro',
    updateChannel: 'subscription',
  },
};

function getAppIdentity(packageInfo = {}) {
  const edition = packageInfo.modagentEdition === 'subscription' ? 'subscription' : 'free';
  const identity = IDENTITIES[edition];
  return {
    ...identity,
    version: packageInfo.version || '0.0.0',
    iconPath: path.join(__dirname, 'assets', 'icons', identity.iconName),
  };
}

module.exports = { IDENTITIES, getAppIdentity };
