export async function runMaintenanceAction(kind, {bridge, timeoutMs = 15000} = {}) {
  const routes = {
    logs: ['openDiagnosticsFolder', []],
    data: ['openMaintenanceFolder', ['data']],
    cache: ['openMaintenanceFolder', ['cache']],
    copyLogs: ['copyMaintenancePath', ['logs']],
  }
  const route = routes[kind]
  if (!route || typeof bridge?.[route[0]] !== 'function') throw new Error('MAINTENANCE_UNAVAILABLE')
  let timer
  try {
    const result = await Promise.race([
      Promise.resolve().then(() => bridge[route[0]](...route[1])),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('MAINTENANCE_TIMEOUT')), timeoutMs) }),
    ])
    // Electron shell.openPath resolves to an empty string on success, not true.
    if (kind === 'copyLogs' ? result?.ok !== true : result !== '') throw new Error('MAINTENANCE_FAILED')
    return result
  } catch (error) {
    throw new Error(error?.message === 'MAINTENANCE_TIMEOUT' ? 'MAINTENANCE_TIMEOUT' : 'MAINTENANCE_FAILED')
  } finally { clearTimeout(timer) }
}

export function maintenanceFailure(error, language) {
  const en = language === 'en'
  if (error?.message === 'MAINTENANCE_TIMEOUT') return en
    ? '[MAINTENANCE_TIMEOUT] The desktop did not confirm in time. The folder may still open or the clipboard may update; check before retrying.'
    : '[MAINTENANCE_TIMEOUT] 桌面未及时确认。目录可能仍会打开或剪贴板稍后更新，请检查后再重试。'
  if (error?.message === 'MAINTENANCE_UNAVAILABLE') return en
    ? '[MAINTENANCE_UNAVAILABLE] This action requires the desktop app. Reopen ModAgent and try again.'
    : '[MAINTENANCE_UNAVAILABLE] 此操作需要桌面应用支持，请重新打开 ModAgent 后再试。'
  return en ? '[MAINTENANCE_FAILED] The desktop action failed. Check folder permissions or clipboard access and try again.'
    : '[MAINTENANCE_FAILED] 桌面操作失败，请检查目录权限或剪贴板访问后再试。'
}
