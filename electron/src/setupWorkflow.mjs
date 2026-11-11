import {saveCredentialSettings, credentialErrorMessage} from './credentialSettings.mjs'
import {LocalApiError, requestLocalJson, localApiFailure} from './components/localApi.mjs'

export async function saveSetupConfiguration(api, body, {store, request = requestLocalJson, credentialTimeoutMs = 20000} = {}) {
  let stage = 'credentials', credentialsSaved = false, timer
  try {
    const saved = await Promise.race([
      saveCredentialSettings(body, store),
      new Promise((_resolve,reject) => {timer=setTimeout(()=>reject(new Error('credential_save_unconfirmed')),credentialTimeoutMs)}),
    ])
    clearTimeout(timer)
    credentialsSaved = Boolean(store)
    stage = 'configuration'
    const result = await request(api+'/config', {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(saved.body),
    })
    if (result?.ok !== true) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
    return {credentialsSaved, status: saved.status}
  } catch (error) {
    // IPC cannot be cancelled from the renderer. A timeout does NOT prove that
    // nothing was written; require a restart before another save attempt.
    const failure = new Error('setup_save_failed')
    failure.stage = stage
    failure.credentialsSaved = credentialsSaved
    failure.restartRequired = error?.message === 'credential_save_unconfirmed'
    failure.cause = error
    throw failure
  } finally { clearTimeout(timer) }
}

export function setupFailureMessage(error, language) {
  const en=language==='en'
  if(error?.restartRequired) return en
    ? '[SETUP_SAVE_UNCONFIRMED] Secure storage did not confirm within 20 seconds. It may still be writing; your input is retained. Restart the app to check the saved state before trying again.'
    : '[SETUP_SAVE_UNCONFIRMED] 加密存储在 20 秒内未确认，后台可能仍在写入，输入已保留。请重启应用检查保存状态后再试。'
  if(error?.stage==='credentials')return '[SETUP_CREDENTIAL_FAILED] '+credentialErrorMessage(error.cause,language)
  return '[SETUP_CONFIG_FAILED] '+(error?.credentialsSaved
    ? (en?'Credentials were saved securely, but app configuration was not confirmed. ':'密钥已安全保存，但应用配置尚未确认成功。')
    : (en?'App configuration was not confirmed. ':'应用配置尚未确认成功。'))+localApiFailure(error?.cause,language)
}
