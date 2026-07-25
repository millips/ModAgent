const path = require('path');
const packageInfo = require('./package.json');
const { getAppIdentity } = require('./appIdentity');

const buildEdition = process.env.MODAGENT_EDITION === 'free' ? 'free' : 'subscription';
const buildPackageInfo = { ...packageInfo, modagentEdition: buildEdition };
const identity = getAppIdentity(buildPackageInfo);
const updateBase = String(process.env.MODAGENT_UPDATE_URL || '').replace(/\/$/, '');
const commonLegalResources = [
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
];
const editionLegalResources = buildEdition === 'free'
  ? [
      {
        from: '../packaging/LICENSE-free.md',
        to: 'legal/LICENSE.md',
      },
    ]
  : [
      {
        from: '../LICENSE.md',
        to: 'legal/LICENSE.md',
      },
      {
        from: '../SUBSCRIPTION-SOFTWARE-LICENSE.md',
        to: 'legal/SUBSCRIPTION-SOFTWARE-LICENSE.md',
      },
      {
        from: '../PROPRIETARY-ASSETS-LICENSE.md',
        to: 'legal/PROPRIETARY-ASSETS-LICENSE.md',
      },
      {
        from: '../SUBSCRIPTION-REFUND-SUPPORT.md',
        to: 'legal/SUBSCRIPTION-REFUND-SUPPORT.md',
      },
    ];

module.exports = {
  appId: identity.appId,
  productName: identity.productName,
  extraMetadata: {
    productName: identity.productName,
    modagentEdition: identity.edition,
    modagentChannel: identity.channel,
  },
  artifactName: `${identity.artifactPrefix}-Setup-${packageInfo.version}.${'${ext}'}`,
  asar: true,
  electronUpdaterCompatibility: '>=2.16',
  directories: {
    output: `release/${identity.updateChannel}`,
  },
  files: [
    'dist/**/*',
    'assets/icons/**/*',
    'main.js',
    'browserLauncher.js',
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
    ...commonLegalResources,
    ...editionLegalResources,
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
    include: identity.isBeta ? 'build/installer-beta.nsh' : 'build/installer.nsh',
    runAfterFinish: true,
  },
  publish: updateBase ? [{ provider: 'generic', url: `${updateBase}/${identity.updateChannel}` }] : null,
};
