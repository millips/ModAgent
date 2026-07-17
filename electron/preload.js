const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('modagent', {
  getApiBase: () => ipcRenderer.sendSync('get-api-base-sync'),
  getApiToken: () => process.env.MODAGENT_API_TOKEN || '',
  getBgDataUrl: filename => ipcRenderer.invoke('get-bg-data-url', filename),
  openExternal: url => ipcRenderer.invoke('open-external', url),
  selectBg: () => ipcRenderer.invoke('select-bg'),
  removeBg: () => ipcRenderer.invoke('remove-bg'),
  saveSecrets: secrets => ipcRenderer.invoke('save-secrets', secrets),
  openDiagnosticsFolder: () => ipcRenderer.invoke('open-diagnostics-folder'),
  exportRuntimeDiagnostics: () => ipcRenderer.invoke('export-runtime-diagnostics'),
  openLegalDocument: filename => ipcRenderer.invoke('open-legal-document', filename),
  checkForAppUpdate: () => ipcRenderer.invoke('check-for-app-update'),
  onUpdateStatus: callback => {
    const listener = (_, detail) => callback(detail);
    ipcRenderer.on('app-update-status', listener);
    return () => ipcRenderer.removeListener('app-update-status', listener);
  },
});
