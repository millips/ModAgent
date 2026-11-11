// Backend heartbeats arrive every 10 seconds. This bounds transport silence,
// not task duration: a live long-running tool must not be aborted by a total timer.
export const CHAT_IDLE_TIMEOUT_MS = 45000

export function createChatWatchdog(controller, {
  timeoutMs = CHAT_IDLE_TIMEOUT_MS, schedule = setTimeout, cancel = clearTimeout,
} = {}) {
  let timer = null
  let disposed = false
  let timedOut = false
  const dispose = () => {
    disposed = true
    if (timer !== null) cancel(timer)
    timer = null
    controller.signal.removeEventListener('abort', dispose)
  }
  const touch = () => {
    if (disposed || controller.signal.aborted) return
    if (timer !== null) cancel(timer)
    timer = schedule(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
  }
  controller.signal.addEventListener('abort', dispose, { once: true })
  touch()
  return { touch, dispose, get timedOut() { return timedOut } }
}

export function chatTimeoutMessage(language) {
  return language === 'en'
    ? '[CHAT_CONNECTION_TIMEOUT] No data or heartbeat from the local service for 45 seconds. The background task may still be running; this does not confirm cancellation or completion. Check the task state before retrying, and do not repeat installation. If the service is unavailable, restart the app and review the task record.'
    : '[CHAT_CONNECTION_TIMEOUT] 已有 45 秒未收到本地服务的数据或心跳。后台任务可能仍在运行；这不代表已取消或已完成。请先查看任务状态再重试，不要重复安装。若本地服务无法连接，请重启应用后检查任务记录。'
}
