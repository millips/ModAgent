import semver from 'semver'

export async function checkDesktopUpdate(bridge, timeoutMs = 20000) {
  if (typeof bridge?.checkForAppUpdate !== 'function') throw Error('UPDATE_UNAVAILABLE')
  let timer
  try {
    const result = await Promise.race([
      Promise.resolve().then(() => bridge.checkForAppUpdate()),
      new Promise((_, reject) => {timer=setTimeout(()=>reject(Error('UPDATE_TIMEOUT')),timeoutMs)}),
    ])
    if (result?.ok !== true) throw Error('UPDATE_FAILED')
    if (result.disabled === true) return {disabled:true}
    if (typeof result.available !== 'boolean' || typeof result.version !== 'string'
      || !semver.valid(result.version)) throw Error('UPDATE_INVALID_RESPONSE')
    return result
  } finally {clearTimeout(timer)}
}
