const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const buildRoot = path.join(root, 'build');
const venv = path.join(buildRoot, 'backend-venv');
const venvPython = path.join(venv, 'Scripts', 'python.exe');
const dist = path.join(buildRoot, 'backend');
const work = path.join(buildRoot, 'pyinstaller');
fs.mkdirSync(buildRoot, { recursive: true });
fs.mkdirSync(dist, { recursive: true });
fs.mkdirSync(work, { recursive: true });

function run(executable, args) {
  const result = spawnSync(executable, args, { cwd: root, stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status || 1);
}

if (!fs.existsSync(venvPython)) {
  run('python', ['-m', 'venv', venv]);
}
run(venvPython, [
  '-m', 'pip', 'install', '--disable-pip-version-check',
  '-r', path.join(root, 'packaging', 'build-requirements.txt'),
]);
run(venvPython, [
  '-m', 'PyInstaller',
  '--noconfirm',
  '--clean',
  '--distpath', dist,
  '--workpath', work,
  path.join(root, 'packaging', 'modagent_backend.spec'),
]);

const executable = path.join(dist, 'ModAgentBackend', 'ModAgentBackend.exe');
if (!fs.existsSync(executable)) {
  console.error(`Backend executable missing: ${executable}`);
  process.exit(1);
}
console.log(`Backend ready: ${executable}`);
