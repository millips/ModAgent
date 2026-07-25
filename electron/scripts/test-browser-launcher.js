const assert = require('assert');
const path = require('path');
const {
  browserCandidates,
  findInstalledBrowser,
  profileDirectory,
} = require('../browserLauncher');

const env = {
  ProgramFiles: 'C:\\Program Files',
  'ProgramFiles(x86)': 'C:\\Program Files (x86)',
  LOCALAPPDATA: 'C:\\Users\\Tester\\AppData\\Local',
};
const edgePath = path.join(
  env['ProgramFiles(x86)'], 'Microsoft', 'Edge', 'Application', 'msedge.exe'
);
const chromePath = path.join(
  env.ProgramFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'
);

let found = findInstalledBrowser(env, 'C:\\Data', value => value === edgePath);
assert.strictEqual(found.id, 'edge');
assert.strictEqual(found.executable, edgePath);

found = findInstalledBrowser(env, 'C:\\Data', value => value === chromePath);
assert.strictEqual(found.id, 'chrome');

found = findInstalledBrowser(env, 'C:\\Data', () => false);
assert.strictEqual(found, null);

assert.strictEqual(browserCandidates(env, 'C:\\Data')[0].id, 'chrome');
assert.strictEqual(
  profileDirectory('C:\\Data', 'edge'),
  path.join('C:\\Data', 'browser_profiles', 'edge')
);

console.log('BROWSER LAUNCHER TESTS PASSED');
