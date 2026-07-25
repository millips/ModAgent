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
  for (const candidate of browserCandidates(env, dataDir)) {
    const executable = candidate.paths.filter(Boolean).find(exists);
    if (executable) return { ...candidate, executable };
  }
  return null;
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
};
