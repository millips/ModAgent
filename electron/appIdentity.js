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
  const requested = process.env.MODAGENT_EDITION || packageInfo.modagentEdition;
  const edition = requested === 'subscription' ? 'subscription' : 'free';
  const requestedChannel = process.env.MODAGENT_CHANNEL || packageInfo.modagentChannel;
  const channel = requestedChannel === 'beta' ? 'beta' : 'stable';
  const base = IDENTITIES[edition];
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
    channel,
    isBeta: channel === 'beta',
    version: packageInfo.version || '0.0.0',
    iconPath: path.join(__dirname, 'assets', 'icons', identity.iconName),
  };
}

module.exports = { IDENTITIES, getAppIdentity };
