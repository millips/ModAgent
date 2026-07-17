const { app, BrowserWindow, ipcMain, shell, dialog, crashReporter } = require('electron');
const { spawn, exec } = require('child_process');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const os = require('os');
const fs = require('fs');
const { getAppIdentity } = require('./appIdentity');
const { createSecurityStore } = require('./securityStore');
const { createRuntimeDiagnostics } = require('./runtimeDiagnostics');
const { setupAutoUpdater } = require('./updater');

const PACKAGE_INFO = require('./package.json');
const IDENTITY = getAppIdentity(PACKAGE_INFO);
const APP_EDITION = IDENTITY.edition;
const IS_SMOKE_TEST = process.argv.includes('--smoke-test');
const DATA_DIR = path.resolve(process.env.MODAGENT_DATA_DIR || path.join(os.homedir(), '.modagent'));
const BG_DIR = path.join(DATA_DIR, 'editions', APP_EDITION, 'bg');
const APP_USER_DATA = IS_SMOKE_TEST && process.env.MODAGENT_USER_DATA_DIR
  ? path.resolve(process.env.MODAGENT_USER_DATA_DIR)
  : path.join(app.getPath('appData'), IDENTITY.userDataFolder);

app.setName(IDENTITY.productName);
app.setPath('userData', APP_USER_DATA);
if (process.platform === 'win32') app.setAppUserModelId(IDENTITY.appId);

const diagnostics = createRuntimeDiagnostics({
  dataDir: DATA_DIR,
  edition: APP_EDITION,
  productName: IDENTITY.productName,
  version: PACKAGE_INFO.version,
});
const { logger } = diagnostics;
const securityStore = createSecurityStore(DATA_DIR, logger);
const launchState = diagnostics.beginLaunch();

fs.mkdirSync(path.join(diagnostics.logsDir, 'crashes'), { recursive: true });
app.setPath('crashDumps', path.join(diagnostics.logsDir, 'crashes'));

let mainWindow = null;
let pythonProcess = null;
let chromeProcess = null;
let backendRestartTimer = null;
let backendRestartCount = 0;
let backendReady = false;
let isQuitting = false;
let activeSecrets = {};
let API_PORT = 18890;
let API_BASE = `http://127.0.0.1:${API_PORT}`;
const CDP_PORT = 18888;
const API_TOKEN = crypto.randomBytes(32).toString('hex');

process.env.MODAGENT_API_TOKEN = API_TOKEN;
process.env.MODAGENT_DATA_DIR = DATA_DIR;
process.env.MODAGENT_EDITION = APP_EDITION;
process.env.MODAGENT_SECURE_SECRETS = '1';

const gotSingleInstanceLock = app.requestSingleInstanceLock({ edition: APP_EDITION });
if (!gotSingleInstanceLock) app.quit();

function findAvailableApiPort(preferredPort) {
  const probe = port => new Promise((resolve, reject) => {
    const server = http.createServer();
    server.unref();
    server.once('error', reject);
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      const selected = server.address().port;
      server.close(() => resolve(selected));
    });
  });
  return probe(preferredPort).catch(error => {
    if (error && error.code === 'EADDRINUSE') return probe(0);
    throw error;
  });
}

function killStaleChrome(callback) {
  const ps = "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*remote-debugging-port=" + CDP_PORT + "*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }";
  exec(`powershell -NoProfile -Command "${ps}"`, () => callback());
}

function startChrome() {
  killStaleChrome(() => {
    exec('reg query "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\chrome.exe" /ve', (error, stdout) => {
      const match = stdout && stdout.match(/REG_SZ\s+(.+)/);
      const chromePath = match ? match[1].trim() : path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe');
      const args = [
        `--remote-debugging-port=${CDP_PORT}`,
        `--user-data-dir=${path.join(DATA_DIR, 'chrome_profile')}`,
        '--window-size=1000,720',
        '--window-position=120,80',
        '--no-first-run',
        '--no-default-browser-check',
        'https://www.nexusmods.com/',
        'https://steamcommunity.com/',
      ];
      try {
        chromeProcess = spawn(chromePath, args, { stdio: 'ignore', detached: true });
        chromeProcess.unref();
        logger.info('Chrome CDP started', { port: CDP_PORT });
      } catch (spawnError) {
        logger.error('Chrome CDP failed to start', spawnError);
      }
    });
  });
}

function backendCommand() {
  if (app.isPackaged) {
    return {
      executable: path.join(process.resourcesPath, 'backend', 'ModAgentBackend.exe'),
      args: ['--host', '127.0.0.1', '--port', String(API_PORT)],
      cwd: DATA_DIR,
    };
  }
  return {
    executable: 'python',
    args: ['-m', 'uvicorn', 'modagent.api:app', '--host', '127.0.0.1', '--port', String(API_PORT)],
    cwd: path.join(__dirname, '..'),
  };
}

function startBackend() {
  if (isQuitting || pythonProcess) return;
  const command = backendCommand();
  if (app.isPackaged && !fs.existsSync(command.executable)) {
    logger.error('Packaged backend executable is missing', command.executable);
    dialog.showErrorBox(`${IDENTITY.productName} ????`, '?????????????????');
    return;
  }
  securityStore.applyToEnvironment(activeSecrets, process.env);
  pythonProcess = spawn(command.executable, command.args, {
    cwd: command.cwd,
    stdio: 'pipe',
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      MODAGENT_API_TOKEN: API_TOKEN,
      MODAGENT_API_PORT: String(API_PORT),
    },
  });
  pythonProcess.stdout.on('data', data => logger.info('[API]', data.toString().trim()));
  pythonProcess.stderr.on('data', data => logger.error('[API]', data.toString().trim()));
  pythonProcess.on('error', error => logger.error('Backend spawn error', error));
  pythonProcess.on('close', code => {
    logger.warn('Backend exited', { code, isQuitting });
    pythonProcess = null;
    backendReady = false;
    if (!isQuitting && backendRestartCount < 2) {
      backendRestartCount += 1;
      backendRestartTimer = setTimeout(() => startBackend(), 1200 * backendRestartCount);
    }
  });
}

function waitForAPI(retries = 30) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts += 1;
      const req = http.get(`${API_BASE}/health`, response => {
        response.resume();
        if (response.statusCode === 200) return resolve();
        if (attempts < retries) setTimeout(check, 1000);
        else reject(new Error('API health check failed'));
      });
      req.on('error', () => {
        if (attempts < retries) setTimeout(check, 1000);
        else reject(new Error('Backend not reachable'));
      });
      req.setTimeout(2000, () => req.destroy());
    };
    check();
  });
}

function verifyBuiltEdition() {
  if (process.argv.includes('--dev')) return true;
  try {
    const marker = require(path.join(__dirname, 'dist', 'edition.json'));
    if (marker.edition === APP_EDITION) return true;
    dialog.showErrorBox(`${IDENTITY.productName} ???????`, `????? ${APP_EDITION}?????? ${marker.edition || 'unknown'}???????`);
  } catch (error) {
    logger.error('Edition marker missing', error);
    dialog.showErrorBox(`${IDENTITY.productName} ??????`, '???????????????');
  }
  return false;
}

async function offerRollbackIfNeeded() {
  if (!launchState.shouldOfferRollback) return false;
  const result = await dialog.showMessageBox({
    type: 'warning',
    title: `${IDENTITY.productName} ????`,
    message: '??????????????',
    detail: launchState.previousVersion
      ? `???????????? ${launchState.previousVersion}?`
      : '?????????????',
    buttons: ['??', '????'],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (result.response !== 0) return false;
  try {
    spawn(launchState.lastGoodInstaller, ['/S'], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
    isQuitting = true;
    diagnostics.markCleanExit();
    app.quit();
    return true;
  } catch (error) {
    logger.error('Rollback installer failed to launch', error);
    dialog.showErrorBox('??????', '????????????????????????');
    return false;
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: IDENTITY.productName,
    icon: IDENTITY.iconPath,
    backgroundColor: '#0d1117',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = url.startsWith('file://') || (process.argv.includes('--dev') && url.startsWith('http://localhost:3000'));
    if (!allowed) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.once('ready-to-show', () => {
    if (!IS_SMOKE_TEST) mainWindow.show();
    if (process.argv.includes('--dev')) mainWindow.webContents.openDevTools();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.webContents.on('render-process-gone', (_, details) => logger.error('Renderer process gone', details));
  mainWindow.webContents.on('console-message', (_, level, message, line, sourceId) => {
    if (level >= 2) logger.error('Renderer console', { message, line, sourceId });
  });
  mainWindow.webContents.on('did-fail-load', (_, code, description, url) => logger.error('Renderer load failed', { code, description, url }));
  mainWindow.webContents.once('did-finish-load', () => {
    if (backendReady) setTimeout(() => diagnostics.markHealthy(), IS_SMOKE_TEST ? 250 : 4000);
    if (IS_SMOKE_TEST) setTimeout(() => app.quit(), 1200);
  });

  if (process.argv.includes('--dev')) await mainWindow.loadURL('http://localhost:3000');
  else await mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
}

function stopChildren() {
  if (backendRestartTimer) clearTimeout(backendRestartTimer);
  if (pythonProcess) {
    pythonProcess.removeAllListeners('close');
    pythonProcess.kill();
    pythonProcess = null;
  }
  if (chromeProcess) {
    try { chromeProcess.kill(); } catch (_) {}
    chromeProcess = null;
  }
}

if (gotSingleInstanceLock) {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    crashReporter.start({
      productName: IDENTITY.productName,
      companyName: 'ModAgent',
      submitURL: '',
      uploadToServer: false,
      compress: true,
    });
    if (await offerRollbackIfNeeded()) return;
    if (!verifyBuiltEdition()) { app.quit(); return; }
    activeSecrets = securityStore.migratePlaintextConfig();
    securityStore.applyToEnvironment(activeSecrets, process.env);
    API_PORT = await findAvailableApiPort(API_PORT);
    API_BASE = `http://127.0.0.1:${API_PORT}`;
    if (!IS_SMOKE_TEST) startChrome();
    startBackend();
    try {
      await waitForAPI(30);
      backendReady = true;
      backendRestartCount = 0;
      logger.info('ModAgent API ready', API_BASE);
    } catch (error) {
      logger.error('Backend failed health check', error);
    }
    await createWindow();
    setupAutoUpdater({ identity: IDENTITY, diagnostics, getMainWindow: () => mainWindow });
  }).catch(error => {
    logger.error('Fatal startup error', error);
    dialog.showErrorBox(`${IDENTITY.productName} ????`, error.message || String(error));
    app.quit();
  });
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  isQuitting = true;
  diagnostics.markCleanExit();
  stopChildren();
});
app.on('activate', () => {
  if (mainWindow === null) createWindow();
});

ipcMain.handle('get-api-base', () => API_BASE);
ipcMain.on('get-api-base-sync', event => { event.returnValue = API_BASE; });
ipcMain.handle('open-external', (_, url) => shell.openExternal(url));
ipcMain.handle('save-secrets', (_, updates = {}) => {
  const allowed = {};
  for (const key of ['nexus_api_key', 'llm_api_key', 'tavily_api_key']) {
    if (Object.prototype.hasOwnProperty.call(updates, key)) allowed[key] = updates[key];
  }
  activeSecrets = securityStore.save(allowed);
  securityStore.applyToEnvironment(activeSecrets, process.env);
  return { ok: true };
});
ipcMain.handle('open-diagnostics-folder', () => shell.openPath(diagnostics.logsDir));
ipcMain.handle('open-legal-document', (_, filename) => {
  const allowed = new Set([
    'PRIVACY.md',
    'THIRD-PARTY-MODS-DISCLAIMER.md',
    'LICENSE.md',
    'THIRD_PARTY_NOTICES.md',
  ]);
  if (!allowed.has(filename)) return 'Document is not available';
  const legalRoot = app.isPackaged
    ? path.join(process.resourcesPath, 'legal')
    : path.resolve(__dirname, '..');
  return shell.openPath(path.join(legalRoot, filename));
});
ipcMain.handle('export-runtime-diagnostics', async () => {
  const result = await dialog.showSaveDialog(mainWindow, {
    title: '?? ModAgent ????',
    defaultPath: path.join(app.getPath('documents'), `${IDENTITY.artifactPrefix}-diagnostics.txt`),
    filters: [{ name: 'Text', extensions: ['txt'] }],
  });
  if (result.canceled || !result.filePath) return null;
  const sections = [];
  sections.push(`${IDENTITY.productName} ${PACKAGE_INFO.version}`);
  sections.push(`Generated: ${new Date().toISOString()}`);
  sections.push(`Edition: ${APP_EDITION}`);
  for (const filename of ['desktop.log', 'updater.log']) {
    const filePath = path.join(diagnostics.logsDir, filename);
    if (fs.existsSync(filePath)) sections.push(`\n===== ${filename} =====\n${fs.readFileSync(filePath, 'utf8').slice(-500000)}`);
  }
  if (fs.existsSync(diagnostics.stateFile)) sections.push(`\n===== runtime-state.json =====\n${fs.readFileSync(diagnostics.stateFile, 'utf8')}`);
  fs.writeFileSync(result.filePath, sections.join('\n'), 'utf8');
  return result.filePath;
});

ipcMain.handle('get-bg-data-url', (_, filename) => {
  const requested = String(filename || '');
  const safeName = path.basename(requested);
  if (!safeName || safeName !== requested) return null;
  const filePath = path.join(BG_DIR, safeName);
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) return null;
  const mime = ({ '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp' })[path.extname(safeName).toLowerCase()];
  if (!mime) return null;
  return `data:${mime};base64,${fs.readFileSync(filePath).toString('base64')}`;
});

ipcMain.handle('select-bg', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '??????',
    filters: [{ name: 'Images', extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const source = result.filePaths[0];
  const extension = path.extname(source);
  fs.rmSync(BG_DIR, { recursive: true, force: true });
  fs.mkdirSync(BG_DIR, { recursive: true });
  const destination = path.join(BG_DIR, `bg_${Date.now()}${extension}`);
  fs.copyFileSync(source, destination);
  return path.basename(destination);
});

ipcMain.handle('remove-bg', () => {
  fs.rmSync(BG_DIR, { recursive: true, force: true });
  return true;
});
