// Verify system-copied candidate packages and create a new manifest (no overwrites).
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const root = path.resolve(__dirname, '..');
const candidate = process.argv[3] || 'core-safety-20260906-r1';
if (!/^[a-z0-9][a-z0-9-]{2,63}$/.test(candidate)) throw Error('Invalid candidate');
const profileCandidate = process.argv[5] || candidate;
if (!/^[a-z0-9][a-z0-9-]{2,63}$/.test(profileCandidate)) throw Error('Invalid profile candidate');
const build = path.join(root, 'build', candidate);
const target = process.argv[2];
if (!target || !path.isAbsolute(target)) throw Error('An absolute new output directory is required');
const guideName = process.argv[4] || 'CORE-SAFETY-20260906-r1.md';
if (!/^[A-Za-z0-9-]+\.md$/.test(guideName)) throw Error('Invalid guide name');
const guide = path.join(root, 'docs', 'testing', guideName);
if (!fs.readFileSync(path.join(target, '先读我-测试说明.txt')).equals(fs.readFileSync(guide))) throw Error('Guide mismatch');
if (fs.existsSync(path.join(target, 'PACKAGE-MANIFEST.json'))) throw Error('Manifest already exists');
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function inventory(dir, prefix = '') {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(item => {
    if (item.isSymbolicLink()) throw Error('Unexpected link: ' + item.name);
    const relative = path.join(prefix, item.name);
    return item.isDirectory() ? inventory(path.join(dir, item.name), relative) : [relative];
  }).sort();
}
const packages = [
  { edition: 'free', folder: 'Free', buildFolder: 'package-free', exe: 'ModAgentBeta-CoreSafety.exe' },
  { edition: 'subscription', folder: 'P', buildFolder: 'package-p', exe: 'ModAgentPBeta-CoreSafety.exe' },
];
for (const pkg of packages) {
  pkg.source = path.join(build, pkg.buildFolder, 'win-unpacked');
  if (!fs.existsSync(path.join(pkg.source, pkg.exe))) throw Error('Missing package ' + pkg.edition);
}
const manifest = {
  candidate, profileCandidate, reusesPriorTestProfile: profileCandidate !== candidate,
  version: '1.6.0-beta.1', createdAt: new Date().toISOString(),
  sourceCommit: execFileSync('git', ['-c', 'safe.directory=' + root.replaceAll('\\', '/'), 'rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  sourceIncludesUncommittedChanges: true,
  scope: 'Isolated candidate; see TESTING.txt for scope. Not complete Agent Core v2; no real-model or real-game acceptance claimed.',
  packages: [],
};
for (const pkg of packages) {
  console.log('Verifying ' + pkg.edition);
  const destination = path.join(target, pkg.folder);
  const files = inventory(pkg.source);
  if (JSON.stringify([...files, 'TESTING.txt'].sort()) !== JSON.stringify(inventory(destination))) throw Error('File count/path mismatch');
  const verified = files.map(relative => {
    const sourceHash = hash(path.join(pkg.source, relative));
    if (sourceHash !== hash(path.join(destination, relative))) throw Error('Copy hash mismatch: ' + relative);
    return { path: relative.replaceAll('\\', '/'), sha256: sourceHash, bytes: fs.statSync(path.join(destination, relative)).size };
  });
  if (!fs.readFileSync(path.join(destination, 'TESTING.txt')).equals(fs.readFileSync(guide))) throw Error('Package guide mismatch');
  const zip = `ModAgent-${pkg.folder}-${candidate}.zip`;
  manifest.packages.push({ edition: pkg.edition, folder: pkg.folder, executable: pkg.exe, verifiedFileCount: files.length, files: verified, zip, zipBytes: fs.statSync(path.join(target, zip)).size, zipSha256: hash(path.join(target, zip)) });
  console.log(`${pkg.folder}: ${files.length} files copy-verified; ${zip}`);
}
fs.writeFileSync(path.join(target, 'PACKAGE-MANIFEST.json'), JSON.stringify(manifest, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify({ target, packages: manifest.packages.map(({ edition, zip, zipBytes, zipSha256 }) => ({ edition, zip, zipBytes, zipSha256 })) }, null, 2));
