const {
  app, BrowserWindow, Menu, ipcMain, shell, dialog, crashReporter,
  Notification, clipboard, safeStorage,
} = require('electron');
const { spawn, exec } = require('child_process');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const os = require('os');
const fs = require('fs');
const { getAppIdentity } = require('./appIdentity');
const { createSecurityStore } = require('./securityStore');
const { createLicenseStore, canUsePBenefits } = require('./licenseStore');
const { createRuntimeDiagnostics, buildDiagnosticReport } = require('./runtimeDiagnostics');
const { setupAutoUpdater } = require('./updater');
const { findInstalledBrowser, profileDirectory } = require('./browserLauncher');

const PACKAGE_INFO = require('./package.json');
const IDENTITY = getAppIdentity(PACKAGE_INFO);
const APP_EDITION = IDENTITY.edition;
const IS_SMOKE_TEST = process.argv.includes('--smoke-test');
// Packaged smoke tests run without a user-visible desktop session on some
// builders. Chromium's GPU subprocess can fail there before the renderer is
// created, which is unrelated to the packaged app's backend/renderer health.
// Keep normal launches hardware accelerated and make only smoke mode headless-
// environment safe.
if (IS_SMOKE_TEST) {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch('disable-gpu');
}
// ModAgent's startup cue is part of the desktop shell, not page media. Allow it
// to begin as soon as the renderer is ready; the renderer still retries safely
// on the first gesture if a device is temporarily unavailable.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
const DEFAULT_DATA_FOLDER = IDENTITY.isBeta ? '.modagent-beta' : '.modagent';
const DATA_DIR = path.resolve(process.env.MODAGENT_DATA_DIR || path.join(os.homedir(), DEFAULT_DATA_FOLDER));
const BG_DIR = path.join(DATA_DIR, 'editions', APP_EDITION, 'bg');
const APP_USER_DATA = IS_SMOKE_TEST && process.env.MODAGENT_USER_DATA_DIR
  ? path.resolve(process.env.MODAGENT_USER_DATA_DIR)
  : path.join(app.getPath('appData'), IDENTITY.userDataFolder);
const TRUSTED_EXTERNAL_HOSTS = new Set([
  'www.nexusmods.com',
  'steamcommunity.com',
  'www.steamcommunity.com',
  'thunderstore.io',
  'www.thunderstore.io',
  'gamebanana.com',
  'www.gamebanana.com',
  'moddb.com',
  'www.moddb.com',
  'app.tavily.com',
  'platform.deepseek.com',
  'platform.openai.com',
  'github.com',
  'www.github.com',
  'afdian.com',
  'www.afdian.com',
  'ifdian.net',
  'www.ifdian.net',
]);
const REVIEWER_LOGINS = new Set(['millips']);

async function openTrustedExternal(rawUrl) {
  try {
    const parsed = new URL(String(rawUrl || ''));
    if (parsed.protocol !== 'https:' || !TRUSTED_EXTERNAL_HOSTS.has(parsed.hostname)) {
      return { ok: false, error: 'Blocked external URL' };
    }
    await shell.openExternal(parsed.toString());
    return { ok: true };
  } catch (_) {
    return { ok: false, error: 'Invalid external URL' };
  }
}

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
const pLicenseStore = createLicenseStore({
  dataDir: DATA_DIR,
  edition: APP_EDITION,
  safeStorage,
  publicKeyPath: path.join(__dirname, 'assets', 'license', 'p-public-key.pem'),
  logger,
});
const launchState = diagnostics.beginLaunch();

fs.mkdirSync(path.join(diagnostics.logsDir, 'crashes'), { recursive: true });
app.setPath('crashDumps', path.join(diagnostics.logsDir, 'crashes'));

let mainWindow = null;
let pythonProcess = null;
let browserProcess = null;
let backendRestartTimer = null;
let backendRestartCount = 0;
let backendReady = false;
let rendererReady = false;
let healthMarkScheduled = false;
let smokeTestCompleted = false;
let smokeTestTimeout = null;
let isQuitting = false;
let replyAttentionPending = false;
let activeSecrets = {};
let API_PORT = 18890;
let API_BASE = `http://127.0.0.1:${API_PORT}`;
const CDP_PORT = 18888;
const API_TOKEN = crypto.randomBytes(32).toString('hex');

process.env.MODAGENT_API_TOKEN = API_TOKEN;
process.env.MODAGENT_DATA_DIR = DATA_DIR;
process.env.MODAGENT_EDITION = APP_EDITION;
process.env.MODAGENT_CHANNEL = IDENTITY.channel;
process.env.MODAGENT_SECURE_SECRETS = '1';

const gotSingleInstanceLock = app.requestSingleInstanceLock({ edition: APP_EDITION });
if (!gotSingleInstanceLock) {
  if (IS_SMOKE_TEST) process.exitCode = 1;
  app.quit();
}

function getReviewerAccess() {
  if (APP_EDITION !== 'subscription') {
    return Promise.resolve({ allowed: false, reason: 'reviewer_requires_p_edition' });
  }
  return new Promise(resolve => {
    const child = spawn('gh', ['api', 'user', '--jq', '.login'], { windowsHide: true });
    let stdout = '';
    const timeout = setTimeout(() => {
      try { child.kill(); } catch (_) {}
    }, 5000);
    child.stdout.on('data', value => { stdout = (stdout + String(value || '')).slice(-256); });
    child.on('error', () => {
      clearTimeout(timeout);
      resolve({ allowed: false, reason: 'github_cli_unavailable' });
    });
    child.on('close', code => {
      clearTimeout(timeout);
      const login = String(stdout || '').trim().toLowerCase();
      resolve({
        allowed: code === 0 && REVIEWER_LOGINS.has(login),
        login: login || '',
        reason: code === 0 ? 'not_an_authorized_reviewer' : 'github_login_required',
      });
    });
  });
}

function fetchPublicGitHubIssue(issueNumber) {
  return new Promise((resolve, reject) => {
    const request = https.get({
      hostname: 'api.github.com',
      path: `/repos/millips/ModAgent-Share/issues/${issueNumber}`,
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': `${IDENTITY.productName} p-share-status`,
      },
    }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', value => { body = (body + value).slice(-512000); });
      response.on('end', () => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          try { resolve(JSON.parse(body)); } catch (_) { reject(new Error('GitHub 返回了无法解析的 Issue 数据')); }
          return;
        }
        const hint = response.statusCode === 403
          ? 'GitHub 403：公开 API 可能限流，请稍后重试或直接打开 Issue 查看。'
          : `GitHub ${response.statusCode || '请求失败'}`;
        reject(new Error(hint));
      });
    });
    request.setTimeout(15000, () => request.destroy(new Error('GitHub 请求超时，请稍后重试。')));
    request.on('error', error => reject(error));
  });
}

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

function killStaleCdpBrowser(callback) {
  const ps = "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('chrome.exe','msedge.exe','brave.exe') -and $_.CommandLine -like '*remote-debugging-port=" + CDP_PORT + "*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }";
  exec(`powershell -NoProfile -Command "${ps}"`, () => callback());
}

function startCdpBrowser() {
  killStaleCdpBrowser(() => {
      const browser = findInstalledBrowser(process.env, DATA_DIR);
      if (!browser) {
        logger.error('No supported Chromium browser found', {
          supported: ['Microsoft Edge', 'Google Chrome', 'Brave'],
          port: CDP_PORT,
        });
        return;
      }
      const args = [
        `--remote-debugging-port=${CDP_PORT}`,
        `--user-data-dir=${profileDirectory(DATA_DIR, browser.id)}`,
        '--window-size=1000,720',
        '--window-position=120,80',
        '--no-first-run',
        '--no-default-browser-check',
        'https://www.nexusmods.com/',
        'https://steamcommunity.com/',
      ];
      try {
        browserProcess = spawn(browser.executable, args, { stdio: 'ignore', detached: true });
        browserProcess.unref();
        browserProcess.once('error', spawnError => {
          logger.error(`${browser.name} CDP failed to start`, spawnError);
        });
        logger.info('CDP browser started', {
          browser: browser.name,
          executable: browser.executable,
          port: CDP_PORT,
        });
      } catch (spawnError) {
        logger.error(`${browser.name} CDP failed to start`, spawnError);
      }
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
    dialog.showErrorBox(`${IDENTITY.productName} 启动失败`, '应用后端组件缺失，请重新安装完整发行包。');
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
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
      MODAGENT_API_TOKEN: API_TOKEN,
      MODAGENT_API_PORT: String(API_PORT),
    },
  });
  pythonProcess.stdout.setEncoding('utf8');
  pythonProcess.stderr.setEncoding('utf8');
  pythonProcess.stdout.on('data', data => logger.info('[API]', data.trim()));
  pythonProcess.stderr.on('data', data => logger.error('[API]', data.trim()));
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

function finishSmokeTest(ok, detail = '') {
  if (!IS_SMOKE_TEST || smokeTestCompleted) return;
  smokeTestCompleted = true;
  if (smokeTestTimeout) {
    clearTimeout(smokeTestTimeout);
    smokeTestTimeout = null;
  }
  if (!ok) {
    process.exitCode = 1;
    logger.error('Packaged smoke test failed', detail);
  } else {
    logger.info('Packaged smoke test passed', {
      rendererReady,
      backendReady,
      api: API_BASE,
    });
  }
  setTimeout(() => app.quit(), 250);
}

function markHealthyWhenReady() {
  if (!backendReady || !rendererReady || healthMarkScheduled) return;
  healthMarkScheduled = true;
  if (IS_SMOKE_TEST) {
    diagnostics.markHealthy();
    finishSmokeTest(true);
    return;
  }
  setTimeout(() => diagnostics.markHealthy(), 4000);
}

function verifyBuiltEdition() {
  if (process.argv.includes('--dev')) return true;
  try {
    const marker = require(path.join(__dirname, 'dist', 'edition.json'));
    if (marker.edition === APP_EDITION && (marker.channel || 'stable') === IDENTITY.channel) return true;
    dialog.showErrorBox(
      `${IDENTITY.productName} 版本校验失败`,
      `当前程序要求 ${APP_EDITION}/${IDENTITY.channel} 资源，但检测到 ${marker.edition || 'unknown'}/${marker.channel || 'stable'}。为防止版本资产混用，应用已停止启动。`,
    );
  } catch (error) {
    logger.error('Edition marker missing', error);
    dialog.showErrorBox(`${IDENTITY.productName} 版本校验失败`, '未找到版本标记文件，请重新安装完整发行包。');
  }
  return false;
}

async function offerRollbackIfNeeded() {
  if (!launchState.shouldOfferRollback) return false;
  const result = await dialog.showMessageBox({
    type: 'warning',
    title: `${IDENTITY.productName} 启动恢复`,
    message: '检测到新版本连续启动失败。',
    detail: launchState.previousVersion
      ? `是否运行已验证的安装程序，回退到 ${launchState.previousVersion}？`
      : '是否运行上一个已验证版本的安装程序？',
    buttons: ['回退', '暂不回退'],
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
    dialog.showErrorBox('回退失败', '无法启动回退安装程序。请导出诊断信息后联系支持。');
    return false;
  }
}

async function createWindow() {
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: IDENTITY.productName,
    icon: IDENTITY.iconPath,
    backgroundColor: '#0d1117',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = url.startsWith('file://') || (process.argv.includes('--dev') && url.startsWith('http://localhost:3000'));
    if (!allowed) {
      event.preventDefault();
      openTrustedExternal(url);
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openTrustedExternal(url);
    return { action: 'deny' };
  });
  mainWindow.once('ready-to-show', () => {
    if (!IS_SMOKE_TEST) mainWindow.show();
    if (process.argv.includes('--dev')) mainWindow.webContents.openDevTools();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.webContents.on('render-process-gone', (_, details) => {
    logger.error('Renderer process gone', details);
    finishSmokeTest(false, `renderer process gone: ${details.reason || 'unknown'}`);
  });
  mainWindow.webContents.on('console-message', (_, level, message, line, sourceId) => {
    if (level >= 2) logger.error('Renderer console', { message, line, sourceId });
  });
  mainWindow.webContents.on('did-fail-load', (_, code, description, url) => {
    logger.error('Renderer load failed', { code, description, url });
    finishSmokeTest(false, `renderer load failed (${code}): ${description}`);
  });
  mainWindow.webContents.once('did-finish-load', () => {
    rendererReady = true;
    markHealthyWhenReady();
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
  if (browserProcess) {
    try { browserProcess.kill(); } catch (_) {}
    browserProcess = null;
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
    if (!verifyBuiltEdition()) {
      if (IS_SMOKE_TEST) finishSmokeTest(false, 'packaged edition verification failed');
      else app.quit();
      return;
    }
    activeSecrets = securityStore.migratePlaintextConfig();
    securityStore.applyToEnvironment(activeSecrets, process.env);
    API_PORT = await findAvailableApiPort(API_PORT);
    API_BASE = `http://127.0.0.1:${API_PORT}`;
    if (IS_SMOKE_TEST) {
      smokeTestTimeout = setTimeout(
        () => finishSmokeTest(false, 'renderer and backend did not become healthy within 45 seconds'),
        45000,
      );
    }
    if (!IS_SMOKE_TEST) startCdpBrowser();
    startBackend();
    await createWindow();
    setupAutoUpdater({ identity: IDENTITY, diagnostics, getMainWindow: () => mainWindow });
    waitForAPI(30).then(() => {
      backendReady = true;
      backendRestartCount = 0;
      logger.info('ModAgent API ready', API_BASE);
      markHealthyWhenReady();
    }).catch(error => {
      logger.error('Backend failed health check', error);
      finishSmokeTest(false, error.message || String(error));
    });
  }).catch(error => {
    logger.error('Fatal startup error', error);
    if (IS_SMOKE_TEST) {
      finishSmokeTest(false, error.message || String(error));
    } else {
      dialog.showErrorBox(`${IDENTITY.productName} 启动失败`, error.message || String(error));
      app.quit();
    }
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
ipcMain.on('get-app-identity-sync', event => {
  event.returnValue = {
    edition: APP_EDITION,
    productName: IDENTITY.productName,
    version: PACKAGE_INFO.version,
    channel: IDENTITY.channel,
  };
});
ipcMain.on('get-p-license-status-sync', event => {
  event.returnValue = pLicenseStore.status();
});
ipcMain.handle('get-p-license-status', () => pLicenseStore.status());
ipcMain.handle('activate-p-license', (_, code) => {
  try {
    const status = pLicenseStore.activate(code);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('p-license-status', status);
    }
    return { ok: true, status };
  } catch (error) {
    logger.warn('ModAgent P activation failed', error.message);
    return { ok: false, error: error.message || '兑换码验证失败' };
  }
});
ipcMain.handle('open-external', (_, url) => openTrustedExternal(url));
ipcMain.handle('read-submission-issue-from-clipboard', () => {
  const text = String(clipboard.readText() || '').trim();
  const match = text.match(/^https:\/\/github\.com\/millips\/ModAgent-Share\/issues\/(\d+)\/?$/i);
  if (!match) {
    return {
      ok: false,
      error: '剪贴板中没有 ModAgent-Share 的 Issue 地址。请在浏览器地址栏按 Ctrl+L、Ctrl+C 后重试。',
    };
  }
  return { ok: true, url: `https://github.com/millips/ModAgent-Share/issues/${match[1]}` };
});
ipcMain.handle('get-reviewer-access', async () => getReviewerAccess());
ipcMain.handle('sync-p-share-issue', async (_, rawUrl) => {
  const match = String(rawUrl || '').trim().match(/^https:\/\/github\.com\/millips\/ModAgent-Share\/issues\/(\d+)\/?$/i);
  if (!match) return { ok: false, error: '投稿链接必须是 ModAgent-Share 的 GitHub Issue 地址。' };
  try {
    const issue = await fetchPublicGitHubIssue(match[1]);
    return { ok: true, issue };
  } catch (error) {
    return { ok: false, error: error.message || '无法读取 GitHub Issue。' };
  }
});
ipcMain.handle('notify-reply-complete', () => {
  const licenseStatus = pLicenseStore.status();
  if (!canUsePBenefits(licenseStatus)) {
    return { ok: false, shown: false, reason: 'p_license_required' };
  }
  if (!mainWindow || mainWindow.isFocused()) return { ok: true, shown: false };
  if (!replyAttentionPending) {
    replyAttentionPending = true;
    if (process.platform === 'win32') mainWindow.flashFrame(true);
    mainWindow.once('focus', () => {
      replyAttentionPending = false;
      if (process.platform === 'win32' && mainWindow) mainWindow.flashFrame(false);
    });
  }
  if (!Notification.isSupported()) return { ok: true, shown: false };
  const notification = new Notification({
    title: IDENTITY.productName,
    body: '回复已经完成，可以回来查看了。',
    silent: true,
  });
  notification.on('click', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  notification.show();
  return { ok: true, shown: true };
});
ipcMain.handle('select-game-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择游戏安装目录',
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const selected = path.resolve(result.filePaths[0]);
  return {
    path: selected,
    suggestedName: path.basename(selected),
  };
});
ipcMain.handle('select-mod-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 Mod 目录（支持 Vortex、MO2、Fluffy 或自定义目录）',
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return { path: path.resolve(result.filePaths[0]) };
});
ipcMain.handle('select-reviewer-repository', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 ModAgent-Share 官方仓库的本地克隆目录',
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const selected = path.resolve(result.filePaths[0]);
  const publisher = path.join(selected, 'scripts', 'publish_collection.py');
  const index = path.join(selected, 'index.json');
  if (!fs.existsSync(publisher) || !fs.existsSync(index)) {
    return { error: '所选目录不是包含 scripts/publish_collection.py 和 index.json 的 ModAgent-Share 仓库。' };
  }
  return { path: selected };
});
ipcMain.handle('select-reviewer-submission', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择已下载的 ModAgent 投稿 JSON',
    filters: [{ name: 'ModAgent JSON', extensions: ['json'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const selected = path.resolve(result.filePaths[0]);
  try {
    const stat = fs.statSync(selected);
    if (stat.size > 1024 * 1024) return { error: '投稿 JSON 超过 1 MiB，已拒绝读取。' };
    const text = fs.readFileSync(selected, 'utf8');
    const manifest = JSON.parse(text);
    return { path: selected, manifest };
  } catch (error) {
    return { error: `无法读取投稿 JSON：${error.message || String(error)}` };
  }
});
ipcMain.handle('load-reviewer-issues', async () => {
  const access = await getReviewerAccess();
  if (!access.allowed) return { ok: false, error: '审核台仅对已登录的授权审核员开放。' };
  const apiPath = '/repos/millips/ModAgent-Share/issues?state=open&per_page=100';
  const parseIssues = (raw) => {
    const issues = JSON.parse(String(raw || '[]'));
    if (!Array.isArray(issues)) throw new Error('GitHub 返回的审核队列格式无效。');
    return issues.filter(item => !item.pull_request);
  };
  const fromGhCli = () => new Promise((resolve, reject) => {
    // Official reviewers normally already use `gh auth login`.  Going through
    // gh keeps the OAuth token inside GitHub CLI instead of exposing it to the
    // renderer or saving another secret in ModAgent.
    const child = spawn('gh', ['api', '-H', 'Accept: application/vnd.github+json', apiPath], {
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', value => { stdout = (stdout + String(value || '')).slice(-512000); });
    child.stderr.on('data', value => { stderr = (stderr + String(value || '')).slice(-8000); });
    child.on('error', error => reject(new Error(`无法调用 GitHub CLI：${error.message || String(error)}`)));
    child.on('close', code => {
      if (code === 0) {
        try { resolve(parseIssues(stdout)); } catch (error) { reject(error); }
        return;
      }
      reject(new Error(stderr.trim() || `GitHub CLI 退出码 ${code}`));
    });
  });
  const fromPublicApi = () => new Promise((resolve, reject) => {
    const request = https.get({
      hostname: 'api.github.com',
      path: apiPath,
      headers: {
        Accept: 'application/vnd.github+json',
        'User-Agent': `${IDENTITY.productName} official-reviewer`,
      },
    }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', value => { body = (body + value).slice(-512000); });
      response.on('end', () => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          try { resolve(parseIssues(body)); } catch (error) { reject(error); }
          return;
        }
        const isRateLimited = response.statusCode === 403 && String(response.headers['x-ratelimit-remaining'] || '') === '0';
        reject(new Error(isRateLimited
          ? 'GitHub 公共 API 额度已用尽；请在本机完成一次 `gh auth login` 后重试。'
          : `GitHub ${response.statusCode || '网络请求失败'}`));
      });
    });
    request.setTimeout(15000, () => request.destroy(new Error('GitHub 请求超时')));
    request.on('error', error => reject(new Error(`GitHub 网络请求失败：${error.message || String(error)}`)));
  });
  try {
    return { ok: true, issues: await fromGhCli(), auth: 'gh' };
  } catch (cliError) {
    try {
      return { ok: true, issues: await fromPublicApi(), auth: 'public' };
    } catch (publicError) {
      return {
        ok: false,
        error: `${publicError.message || String(publicError)}（CLI 回退信息：${cliError.message || String(cliError)}）`,
      };
    }
  }
});
ipcMain.handle('reviewer-publish-collection', async (_, payload = {}) => {
  const access = await getReviewerAccess();
  if (!access.allowed) return { ok: false, error: '审核台仅对已登录的授权审核员开放。' };
  const repository = path.resolve(String(payload.repository || ''));
  const submission = path.resolve(String(payload.submissionPath || ''));
  const issueUrl = String(payload.issueUrl || '').trim();
  const publisher = path.join(repository, 'scripts', 'publish_collection.py');
  if (!fs.existsSync(publisher) || !fs.existsSync(path.join(repository, 'index.json'))) {
    return { ok: false, error: '审核仓库路径无效。请重新选择 ModAgent-Share 本地克隆目录。' };
  }
  if (!submission.toLowerCase().endsWith('.json') || !fs.existsSync(submission)) {
    return { ok: false, error: '投稿 JSON 路径无效。' };
  }
  if (!/^https:\/\/github\.com\/millips\/ModAgent-Share\/issues\/\d+\/?$/i.test(issueUrl)) {
    return { ok: false, error: 'Issue 链接必须属于 millips/ModAgent-Share。' };
  }
  const args = [publisher, '--submission', submission, '--issue-url', issueUrl];
  if (payload.publish === true) args.push('--publish');
  return await new Promise(resolve => {
    const child = spawn('python', args, { cwd: repository, windowsHide: true });
    let output = '';
    const append = value => { output = (output + String(value || '')).slice(-64000); };
    child.stdout.on('data', append);
    child.stderr.on('data', append);
    const timeout = setTimeout(() => {
      try { child.kill(); } catch (_) {}
    }, 120000);
    child.on('error', error => {
      clearTimeout(timeout);
      resolve({ ok: false, error: `无法启动审核工具：${error.message || String(error)}` });
    });
    child.on('close', code => {
      clearTimeout(timeout);
      resolve({ ok: code === 0, code, output, error: code === 0 ? '' : '审核工具未通过校验或未能完成入库。' });
    });
  });
});
ipcMain.handle('select-game-executable', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择游戏主程序',
    filters: [{ name: 'Windows executable', extensions: ['exe'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const executable = path.resolve(result.filePaths[0]);
  return {
    path: path.dirname(executable),
    executable,
    suggestedName: path.basename(executable, path.extname(executable)),
  };
});
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
ipcMain.handle('open-maintenance-folder', (_, kind) => {
  const folders = {
    logs: diagnostics.logsDir,
    data: DATA_DIR,
    cache: app.getPath('sessionData'),
  };
  const target = folders[String(kind || '')];
  if (!target) return 'Unsupported maintenance folder';
  fs.mkdirSync(target, { recursive: true });
  return shell.openPath(target);
});
ipcMain.handle('copy-maintenance-path', (_, kind) => {
  const folders = {
    logs: diagnostics.logsDir,
    data: DATA_DIR,
    cache: app.getPath('sessionData'),
  };
  const target = folders[String(kind || '')];
  if (!target) return { ok: false, error: 'Unsupported maintenance folder' };
  clipboard.writeText(target);
  return { ok: true, path: target };
});
ipcMain.handle('open-legal-document', (_, filename) => {
  const allowed = new Set([
    'PRIVACY.md',
    'THIRD-PARTY-MODS-DISCLAIMER.md',
    'SUBSCRIPTION-REFUND-SUPPORT.md',
    'SUBSCRIPTION-SOFTWARE-LICENSE.md',
    'PROPRIETARY-ASSETS-LICENSE.md',
    'THIRD_PARTY_NOTICES.md',
    'LICENSE.md',
  ]);
  const requested = path.basename(String(filename || ''));
  if (!allowed.has(requested)) return 'Unsupported legal document';
  const legalPath = app.isPackaged
    ? path.join(process.resourcesPath, 'legal', requested)
    : path.resolve(__dirname, '..', requested);
  if (!fs.existsSync(legalPath)) return 'Legal document is missing';
  return shell.openPath(legalPath);
});
ipcMain.handle('export-runtime-diagnostics', async () => {
  const report = buildDiagnosticReport({
    diagnostics, productName: IDENTITY.productName,
    version: PACKAGE_INFO.version, edition: APP_EDITION,
  });
  const preview = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: '预览脱敏后的诊断信息',
    message: '诊断内容已统一脱敏。请在保存前检查以下预览。',
    detail: report.slice(0, 12000) + (report.length > 12000 ? '\n\n[预览已截断，导出文件包含完整脱敏内容]' : ''),
    buttons: ['继续保存', '取消'],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (preview.response !== 0) return null;
  const result = await dialog.showSaveDialog(mainWindow, {
    title: '导出 ModAgent 诊断信息',
    defaultPath: path.join(app.getPath('documents'), `${IDENTITY.artifactPrefix}-diagnostics.txt`),
    filters: [{ name: 'Text', extensions: ['txt'] }],
  });
  if (result.canceled || !result.filePath) return null;
  fs.writeFileSync(result.filePath, report, 'utf8');
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
    title: '选择背景图片',
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
