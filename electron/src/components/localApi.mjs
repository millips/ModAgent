export class LocalApiError extends Error {
  constructor(code, status = null) {
    super(code)
    this.name = 'LocalApiError'
    this.code = code
    this.status = status
  }
}

// Bounded JSON operations only. Long-running work belongs to task/SSE APIs.
export async function requestLocalJson(url, options = {}, {timeoutMs = 15000, fetchImpl = fetch} = {}) {
  const controller = new AbortController()
  const parent = options.signal
  let timedOut = false
  const abort = () => controller.abort()
  if (parent?.aborted) abort()
  else parent?.addEventListener('abort', abort, {once:true})
  const timer = setTimeout(() => { timedOut = true; abort() }, timeoutMs)
  try {
    const response = await fetchImpl(url, {...options, signal:controller.signal})
    if (!response.ok) throw new LocalApiError('LOCAL_API_HTTP', response.status)
    try { return await response.json() }
    catch (error) {
      if (controller.signal.aborted) throw error
      throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
    }
  } catch (error) {
    if (timedOut) throw new LocalApiError('LOCAL_API_TIMEOUT')
    if (parent?.aborted) throw error
    if (error instanceof LocalApiError) throw error
    throw new LocalApiError('LOCAL_API_UNAVAILABLE')
  } finally {
    clearTimeout(timer)
    parent?.removeEventListener('abort', abort)
    controller.abort()
  }
}

export function localApiFailure(error, language, {mutation = false} = {}) {
  const en = language === 'en'
  if (mutation) {
    const status = Number.isInteger(error?.status) && error.status >= 100 && error.status <= 599 ? error.status : '?'
    const reason = error?.code === 'LOCAL_API_HTTP' ? `HTTP ${status}`
      : error?.code === 'LOCAL_API_TIMEOUT' ? (en ? 'response timeout' : '响应超时')
      : error?.code === 'LOCAL_API_INVALID_RESPONSE' ? (en ? 'invalid response' : '返回数据异常')
      : (en ? 'connection interrupted or unavailable' : '连接中断或不可用')
    return en
      ? `Result unconfirmed (${reason}). The service may already have changed files or settings, or may still be running. Check the task status and current Mod/configuration state before retrying; do not repeat the operation blindly.`
      : `操作结果未确认（${reason}）。后台可能已经修改文件或配置，也可能仍在执行。请先核对任务状态及当前 Mod/配置，再决定是否重试，不要直接重复操作。`
  }
  if (error?.code === 'GAME_SELECTION_MISMATCH') return en
    ? 'The service replied, but the active game does not match the selected game. Editing remains locked; recheck the game before continuing.'
    : '后台已回复，但当前游戏与所选游戏不一致。操作继续锁定，请重新核验游戏后再继续。'
  if (error?.code === 'GAME_SELECTION_INVALID') return en
    ? 'The game identity or installation folder is incomplete. Check the game entry before trying again.'
    : '游戏信息或安装目录不完整，请检查游戏条目后再试。'
  if (error?.code === 'LOCAL_API_TIMEOUT') return en
    ? 'The local service did not reply in time. The operation may still have reached it; check the current state before retrying.'
    : '本地服务未及时回复。操作可能已送达后台，请先检查当前状态再重试。'
  if (error?.code === 'LOCAL_API_HTTP') return en
    ? `The local service returned HTTP ${error.status}. Check the service and retry.`
    : `本地服务返回 HTTP ${error.status}，请检查服务状态后重试。`
  if (error?.code === 'LOCAL_API_INVALID_RESPONSE') return en
    ? 'The local service returned an invalid result. No success has been confirmed.'
    : '本地服务返回的数据异常，尚未确认操作成功。'
  return en ? 'Cannot reach the local service. Check the app connection and retry.' : '无法连接本地服务，请检查应用连接后重试。'
}
