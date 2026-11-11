const fs = require('fs');
const path = require('path');

function browserCandidates(env = process.env, dataDir = '') {
  const programFiles = env.ProgramFiles || 'C:\\Program Files';
  const programFilesX86 = env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const localAppData = env.LOCALAPPDATA || '';
  const candidates = [
    {
      id: 'chrome',
      name: 'Google Chrome',
      processName: 'chrome.exe',
      paths: [
        path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        path.join(programFilesX86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        localAppData && path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      ],
    },
    {
      id: 'edge',
      name: 'Microsoft Edge',
      processName: 'msedge.exe',
      paths: [
        path.join(programFilesX86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        path.join(programFiles, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        localAppData && path.join(localAppData, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
      ],
    },
    {
      id: 'brave',
      name: 'Brave',
      processName: 'brave.exe',
      paths: [
        path.join(programFiles, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
        path.join(programFilesX86, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
        localAppData && path.join(localAppData, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      ],
    },
  ];

  // Chrome is the primary CDP browser. Edge and Brave are compatibility
  // fallbacks only; this avoids silently switching users to Edge each restart.
  return candidates;
}

function findInstalledBrowser(env = process.env, dataDir = '', exists = fs.existsSync) {
  return installedBrowsers(env, dataDir, exists)[0] || null;
}

function readBrowserPreference(dataDir) {
  try {
    const value = JSON.parse(fs.readFileSync(path.join(dataDir, 'browser-preference.json'), 'utf8'));
    const browser = browserCandidates().find(item => item.id === value.id);
    if (!browser || typeof value.executable !== 'string'
        || path.basename(value.executable).toLowerCase() !== browser.processName) return {};
    return value;
  } catch { return {}; }
}

function installedBrowsers(env = process.env, dataDir = '', exists = fs.existsSync, preference = readBrowserPreference(dataDir)) {
  const found = browserCandidates(env, dataDir).map(candidate => {
    const custom = preference.id === candidate.id && typeof preference.executable === 'string'
      && path.basename(preference.executable).toLowerCase() === candidate.processName ? preference.executable : '';
    const executable = [custom, ...candidate.paths].filter(Boolean).find(exists);
    return executable ? {...candidate, executable} : null;
  }).filter(Boolean);
  // A working Edge/Brave profile must not change just because Chrome was installed later.
  return found.sort((a, b) => Number(b.id === preference.id) - Number(a.id === preference.id));
}

function saveBrowserPreference(dataDir, value) {
  fs.mkdirSync(dataDir, {recursive:true});
  const file = path.join(dataDir, 'browser-preference.json');
  const temp = file + '.' + require('crypto').randomUUID() + '.tmp';
  try {
    fs.writeFileSync(temp, JSON.stringify(value), {flag:'wx'});
    fs.renameSync(temp, file);
  } finally { try { fs.unlinkSync(temp); } catch {} }
}

function profileDirectory(dataDir, browserId) {
  if (browserId === 'chrome' && fs.existsSync(path.join(dataDir, 'chrome_profile'))) {
    return path.join(dataDir, 'chrome_profile');
  }
  return path.join(dataDir, 'browser_profiles', browserId);
}

module.exports = {
  browserCandidates,
  findInstalledBrowser,
  profileDirectory,
  installedBrowsers,
  readBrowserPreference,
  saveBrowserPreference,
};
