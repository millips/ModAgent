const path = require('path');
const packageInfo = require('./package.json');
const { getAppIdentity } = require('./appIdentity');

const identity = getAppIdentity(packageInfo);
const updateBase = String(process.env.MODAGENT_UPDATE_URL || '').replace(/\/$/, '');

module.exports = {
  appId: identity.appId,
  productName: identity.productName,
  artifactName: `${identity.artifactPrefix}-Setup-${packageInfo.version}.${'${ext}'}`,
  asar: true,
  electronUpdaterCompatibility: '>=2.16',
  directories: {
    output: `release/${identity.edition}`,
  },
  files: [
    'dist/**/*',
    'assets/icons/**/*',
    'main.js',
    'preload.js',
    'appIdentity.js',
    'securityStore.js',
    'runtimeDiagnostics.js',
    'updater.js',
    'package.json',
  ],
  extraResources: [
    {
      from: '../build/backend/ModAgentBackend',
      to: 'backend',
      filter: ['**/*'],
    },
    {
      from: '../LICENSE.md',
      to: 'legal/LICENSE.md',
    },
    {
      from: '../LICENSE-GPL-3.0.txt',
      to: 'legal/LICENSE-GPL-3.0.txt',
    },
    {
      from: '../THIRD_PARTY_NOTICES.md',
      to: 'legal/THIRD_PARTY_NOTICES.md',
    },
    {
      from: '../PRIVACY.md',
      to: 'legal/PRIVACY.md',
    },
    {
      from: '../THIRD-PARTY-MODS-DISCLAIMER.md',
      to: 'legal/THIRD-PARTY-MODS-DISCLAIMER.md',
    },
  ],
  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
    icon: identity.iconPath,
    executableName: identity.executableName,
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowElevation: true,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: identity.productName,
    uninstallDisplayName: identity.productName,
    deleteAppDataOnUninstall: false,
    runAfterFinish: true,
  },
  publish: updateBase ? [{ provider: 'generic', url: `${updateBase}/${identity.updateChannel}` }] : null,
};
