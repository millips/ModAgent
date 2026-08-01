const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('modagent', {
  getApiBase: () => ipcRenderer.sendSync('get-api-base-sync'),
  getAppIdentity: () => ipcRenderer.sendSync('get-app-identity-sync'),
  getApiToken: () => process.env.MODAGENT_API_TOKEN || '',
  getPLicenseStatusSync: () => ipcRenderer.sendSync('get-p-license-status-sync'),
  getPLicenseStatus: () => ipcRenderer.invoke('get-p-license-status'),
  activatePLicense: code => ipcRenderer.invoke('activate-p-license', code),
  onPLicenseStatus: callback => {
    const listener = (_, detail) => callback(detail);
    ipcRenderer.on('p-license-status', listener);
    return () => ipcRenderer.removeListener('p-license-status', listener);
  },
  getBgDataUrl: filename => ipcRenderer.invoke('get-bg-data-url', filename),
  openExternal: url => ipcRenderer.invoke('open-external', url),
  readSubmissionIssueFromClipboard: () => ipcRenderer.invoke('read-submission-issue-from-clipboard'),
  getReviewerAccess: () => ipcRenderer.invoke('get-reviewer-access'),
  syncPShareIssue: url => ipcRenderer.invoke('sync-p-share-issue', url),
  lookupPShareCode: url => ipcRenderer.invoke('lookup-p-share-code', url),
  selectGameDirectory: () => ipcRenderer.invoke('select-game-directory'),
  selectModDirectory: () => ipcRenderer.invoke('select-mod-directory'),
  selectReviewerRepository: () => ipcRenderer.invoke('select-reviewer-repository'),
  selectReviewerSubmission: () => ipcRenderer.invoke('select-reviewer-submission'),
  loadReviewerIssues: () => ipcRenderer.invoke('load-reviewer-issues'),
  reviewerPublishCollection: payload => ipcRenderer.invoke('reviewer-publish-collection', payload),
  selectGameExecutable: () => ipcRenderer.invoke('select-game-executable'),
  selectBg: () => ipcRenderer.invoke('select-bg'),
  removeBg: () => ipcRenderer.invoke('remove-bg'),
  saveSecrets: secrets => ipcRenderer.invoke('save-secrets', secrets),
  openDiagnosticsFolder: () => ipcRenderer.invoke('open-diagnostics-folder'),
  openMaintenanceFolder: kind => ipcRenderer.invoke('open-maintenance-folder', kind),
  copyMaintenancePath: kind => ipcRenderer.invoke('copy-maintenance-path', kind),
  openLegalDocument: filename => ipcRenderer.invoke('open-legal-document', filename),
  exportRuntimeDiagnostics: () => ipcRenderer.invoke('export-runtime-diagnostics'),
  checkForAppUpdate: () => ipcRenderer.invoke('check-for-app-update'),
  notifyReplyComplete: () => ipcRenderer.invoke('notify-reply-complete'),
  onUpdateStatus: callback => {
    const listener = (_, detail) => callback(detail);
    ipcRenderer.on('app-update-status', listener);
    return () => ipcRenderer.removeListener('app-update-status', listener);
  },
});
