export async function startRenderer({load, timeoutMs = 20000, documentRef = document, reload = () => window.location.reload()}) {
  let timer
  try {
    const entry = await Promise.race([
      Promise.resolve().then(load),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('UI_STARTUP_TIMEOUT')), timeoutMs) }),
    ])
    if (typeof entry?.mountApp !== 'function') throw new Error('UI_STARTUP_FAILED')
    await entry.mountApp()
    return true
  } catch (error) {
    const code = error?.message === 'UI_STARTUP_TIMEOUT' ? 'UI_STARTUP_TIMEOUT' : 'UI_STARTUP_FAILED'
    const container = documentRef.getElementById('root')
    if (!container) return false
    const panel = documentRef.createElement('main')
    panel.setAttribute('role', 'alert')
    panel.style.cssText = 'min-height:100vh;box-sizing:border-box;padding:40px 24px;background:#111827;color:#e5e7eb;font:16px/1.8 system-ui,sans-serif'
    for (const text of [
      'ModAgent 启动未完成 / ModAgent could not finish starting',
      `[${code}]`,
      '界面资源未及时加载或初始化失败。此恢复页不会清除已保存的配置或游戏文件。',
      'Interface resources did not load in time or initialization failed. This recovery screen does not clear saved settings or game files.',
      '后台任务可能仍在运行。重新加载不是取消任务；恢复后请先核对状态。若反复出现，请保留错误代码和发生时间，尝试重新打开应用或重新解压完整程序目录。',
      'Background tasks may still be running. Reloading does not cancel them; verify the state after recovery. If this recurs, keep the error code and time, then reopen the app or extract the complete app folder again.',
    ]) {
      const paragraph = documentRef.createElement('p')
      paragraph.textContent = text
      panel.appendChild(paragraph)
    }
    const button = documentRef.createElement('button')
    button.textContent = '重新加载界面 / Reload interface'
    button.style.cssText = 'padding:12px 18px;color:white;background:#23334d;border:1px solid #70829c;border-radius:8px;cursor:pointer'
    button.addEventListener('click', reload)
    panel.appendChild(button)
    container.replaceChildren(panel)
    // Do not display or log exception messages that may contain local paths or tokens.
    return false
  } finally { clearTimeout(timer) }
}
