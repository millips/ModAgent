const path = require('path');
const { app, dialog, ipcMain } = require('electron');
const electronLog = require('electron-log');

function setupAutoUpdater({ identity, diagnostics, getMainWindow }) {
  if (!app.isPackaged) return null;
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
      title: `${identity.productName} ?????`,
      message: `?? ${info.version} ??????`,
      detail: '?????????????????????',
      buttons: ['????', '??'],
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

module.exports = { setupAutoUpdater };
