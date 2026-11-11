import {requestLocalJson, LocalApiError} from './components/localApi.mjs'

export function validateRuntimeStatus(status) {
  if (!status || typeof status.llm_model !== 'string' || typeof status.llm_endpoint !== 'string'
      || typeof status.llm_set !== 'boolean' || typeof status.api_key_set !== 'boolean'
      || typeof status.tavily_set !== 'boolean') throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  return status
}

export async function readRuntimeStatus(api, {signal, request = requestLocalJson} = {}) {
  const health = await request(api + '/health', {signal})
  if (health?.ok !== true) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  // A failed status request is not evidence that credentials are missing.
  return validateRuntimeStatus(await request(api + '/status', {signal}))
}
