// Scoped r10 delivery: verify actual packages, then copy to a NEW desktop folder.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const build = path.join(root, 'build/reliability-r10');
const target = 'C:/Users/Administrator/Desktop/ModAgent 链路验收测试包 20260908-r10';
const guide = path.join(root, 'TESTING-R10.md');
const verifyCopied = process.argv.includes('--verify-copied');
const packages = [
  { edition: 'subscription', folder: 'P', build: 'package-p', exe: 'ModAgentPBeta-CoreSafety.exe' },
  { edition: 'free', folder: 'Free', build: 'package-free', exe: 'ModAgentBeta-CoreSafety.exe' },
];
if (fs.existsSync(target) && !verifyCopied) throw Error('Refusing to overwrite existing delivery');
if (fs.existsSync(path.join(target, 'PACKAGE-MANIFEST.json'))) throw Error('Delivery already finalized');
const sha256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function inventory(dir, prefix = '') {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    if (entry.isSymbolicLink()) throw Error('Unexpected link: ' + entry.name);
    const relative = path.join(prefix, entry.name);
    return entry.isDirectory() ? inventory(path.join(dir, entry.name), relative) : [relative];
  }).sort();
}
for (const pkg of packages) {
  pkg.source = path.join(build, pkg.build, 'win-unpacked');
  const exe = path.join(pkg.source, pkg.exe);
  if (!fs.existsSync(exe)) throw Error('Missing executable: ' + exe);
  if (verifyCopied) {
    const evidence = fs.readFileSync(path.join(build, 'packaged-smoke-' + pkg.edition + '.log'), 'utf8');
    if (!evidence.includes('CREDENTIAL IMPORT + ENCRYPTED RESTART + SETUP BYPASS PASSED')
      || !evidence.includes('PACKAGED ' + pkg.edition.toUpperCase() + ' SMOKE TEST PASSED')) throw Error('Missing smoke evidence');
    continue;
  }
  console.log('Checking packaged startup and synthetic credential restart: ' + pkg.edition);
  const result = spawnSync(process.execPath, [path.join(root, 'electron/scripts/test-packaged-smoke.js'),
    '--edition', pkg.edition, '--exe', exe, '--credentials'],
  { cwd: root, encoding: 'utf8', timeout: 210000, windowsHide: true });
  const output = (result.stdout || '') + (result.stderr || '');
  fs.writeFileSync(path.join(build, 'packaged-smoke-' + pkg.edition + '.log'), output);
  process.stdout.write(output);
  if (result.error) throw result.error;
  if (result.status !== 0 || !output.includes('CREDENTIAL IMPORT + ENCRYPTED RESTART + SETUP BYPASS PASSED')) {
    throw Error('Package smoke failed: ' + pkg.edition);
  }
}
if (!verifyCopied) {
  fs.mkdirSync(target, { recursive: false });
  fs.copyFileSync(guide, path.join(target, '先读我-测试任务单.md'));
}
if (!fs.readFileSync(guide).equals(fs.readFileSync(path.join(target, '先读我-测试任务单.md')))) throw Error('Guide mismatch');
const manifest = { candidate: 'reliability-r10', version: '1.6.0-beta.1', createdAt: new Date().toISOString(),
  includesUncommittedSource: true, newIsolatedProfile: false, profileCandidate: 'reliability-r9', automaticUpdates: false,
  limits: 'No real-model search accuracy or real-game acceptance claimed; full cross-restart task recovery remains incomplete.', packages: [] };
for (const pkg of packages) {
  const destination = path.join(target, pkg.folder);
  if (!verifyCopied) fs.cpSync(pkg.source, destination, { recursive: true, force: false, errorOnExist: true });
  const files = inventory(pkg.source);
  if (JSON.stringify(files) !== JSON.stringify(inventory(destination))) throw Error('Copy inventory mismatch');
  const records = files.map(relative => {
    const hash = sha256(path.join(pkg.source, relative));
    if (hash !== sha256(path.join(destination, relative))) throw Error('Copy hash mismatch: ' + relative);
    return { path: relative.replaceAll('\\', '/'), sha256: hash };
  });
  fs.copyFileSync(guide, path.join(destination, 'TESTING.md'));
  manifest.packages.push({ edition: pkg.edition, folder: pkg.folder, executable: pkg.exe,
    startupAndSyntheticCredentialRestartPassed: true, verifiedFiles: records.length,
    exeSha256: sha256(path.join(destination, pkg.exe)),
    appAsarSha256: sha256(path.join(destination, 'resources/app.asar')),
    backendSha256: sha256(path.join(destination, 'resources/backend/ModAgentBackend.exe')), files: records });
  console.log('Delivered and hash-verified: ' + path.join(destination, pkg.exe));
}
fs.writeFileSync(path.join(target, 'PACKAGE-MANIFEST.json'), JSON.stringify(manifest, null, 2), { flag: 'wx' });
console.log('DELIVERY VERIFIED: ' + target);
