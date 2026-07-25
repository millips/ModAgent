const fs = require('fs');
const https = require('https');
const path = require('path');
const { app, dialog, ipcMain } = require('electron');
const electronLog = require('electron-log');

function updateConfigurationPath(resourcesPath) {
  return path.join(resourcesPath, 'app-update.yml');
}

function hasUpdateConfiguration(resourcesPath, existsSync = fs.existsSync) {
  return existsSync(updateConfigurationPath(resourcesPath));
}

function compareVersions(left, right) {
  const parse = value => String(value || '').replace(/^v/i, '').split('.')
    .map(part => Number.parseInt(part, 10) || 0)
  const a = parse(left)
  const b = parse(right)
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if ((a[index] || 0) !== (b[index] || 0)) return (a[index] || 0) - (b[index] || 0)
  }
  return 0
}

function fetchJson(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (!url || redirects > 4) return reject(new Error('更新清单地址无效'))
    const request = https.get(url, {
      headers: {
        Accept: 'application/json',
        'User-Agent': `ModAgent/${app.getVersion()}`,
      },
      timeout: 8000,
    }, response => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode) && response.headers.location) {
        response.resume()
        const next = new URL(response.headers.location, url).toString()
        resolve(fetchJson(next, redirects + 1))
        return
      }
      if (response.statusCode !== 200) {
        response.resume()
        reject(new Error(`更新清单返回 ${response.statusCode}`))
        return
      }
      let body = ''
      response.setEncoding('utf8')
      response.on('data', chunk => {
        body += chunk
        if (body.length > 128 * 1024) request.destroy(new Error('更新清单过大'))
      })
      response.on('end', () => {
        try { resolve(JSON.parse(body)) } catch (_) { reject(new Error('更新清单格式无效')) }
      })
    })
    request.on('timeout', () => request.destroy(new Error('检查更新超时')))
    request.on('error', reject)
  })
}

function setupManualUpdateChecker({ identity, diagnostics, getMainWindow }) {
  const check = async () => {
    const manifest = await fetchJson(identity.manualUpdateManifestUrl)
    if (manifest.channel && manifest.channel !== identity.updateChannel) {
      throw new Error('更新清单渠道不匹配')
    }
    const latest = String(manifest.latest_version || '')
    if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(latest)) {
      throw new Error('更新清单版本号无效')
    }
    const available = compareVersions(latest, app.getVersion()) > 0
    const result = {
      ok: true,
      available,
      currentVersion: app.getVersion(),
      version: latest,
      severity: manifest.severity || 'normal',
      minimumSafeVersion: manifest.minimum_safe_version || '',
      message: String(manifest.message || ''),
      downloadPage: String(manifest.download_page || ''),
    }
    diagnostics.logger.info('Manual update manifest checked', result)
    const window = getMainWindow()
    if (available && window && !window.isDestroyed()) {
      window.webContents.send('app-update-status', { status: 'available', ...result })
    }
    return result
  }

  ipcMain.handle('check-for-app-update', async () => {
    try {
      return await check()
    } catch (error) {
      diagnostics.logger.warn('Manual update check failed', error.message)
      return { ok: false, error: error.message }
    }
  })
  setTimeout(() => check().catch(() => {}), 8000)
  return { check }
}

function setupAutoUpdater({ identity, diagnostics, getMainWindow }) {
  if (!app.isPackaged) return null;
  if (!hasUpdateConfiguration(process.resourcesPath)) {
    diagnostics.logger.info('Automatic updater disabled; manual update manifest enabled', {
      channel: identity.updateChannel,
    });
    return setupManualUpdateChecker({ identity, diagnostics, getMainWindow });
  }
  let autoUpdater;
  try {
    ({ autoUpdater } = require('electron-updater'));
  } catch (error) {
    diagnostics.logger.error('Auto updater unavailable', error);
    return null;
  }

  electronLog.transports.file.resolvePathFn = () => path.join(diagnostics.logsDir, 'updater.log');
  electronLog.transports.file.level = 'info';
  autoUpdater.logger = electronLog;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  const send = (status, detail = {}) => {
    diagnostics.logger.info('Updater', status, detail);
    const window = getMainWindow();
    if (window && !window.isDestroyed()) window.webContents.send('app-update-status', { status, ...detail });
  };

  autoUpdater.on('checking-for-update', () => send('checking'));
  autoUpdater.on('update-available', info => send('available', { version: info.version }));
  autoUpdater.on('update-not-available', info => send('current', { version: info.version }));
  autoUpdater.on('download-progress', progress => send('downloading', { percent: progress.percent }));
  autoUpdater.on('error', error => send('error', { message: error.message }));
  autoUpdater.on('update-downloaded', async info => {
    const installer = info.downloadedFile || info.files?.[0]?.url || '';
    if (installer && typeof installer === 'string') {
      try { diagnostics.recordDownloadedInstaller(installer, info.version); } catch (error) {
        diagnostics.logger.error('Failed to cache installer for rollback', error);
      }
    }
    send('downloaded', { version: info.version });
    const result = await dialog.showMessageBox(getMainWindow(), {
      type: 'info',
      title: `${identity.productName} 更新已下载`,
      message: `版本 ${info.version} 已准备就绪。`,
      detail: '现在重启将安装更新；也可以稍后在退出应用时安装。',
      buttons: ['立即重启安装', '稍后'],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    });
    if (result.response === 0) autoUpdater.quitAndInstall(false, true);
  });

  ipcMain.handle('check-for-app-update', async () => {
    try {
      const result = await autoUpdater.checkForUpdates();
      return { ok: true, version: result?.updateInfo?.version || app.getVersion() };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  });

  setTimeout(() => {
    autoUpdater.checkForUpdatesAndNotify().catch(error => diagnostics.logger.warn('Startup update check failed', error.message));
  }, 8000);

  return autoUpdater;
}

module.exports = {
  setupAutoUpdater,
  setupManualUpdateChecker,
  compareVersions,
  fetchJson,
  hasUpdateConfiguration,
  updateConfigurationPath,
};
