import {LocalApiError} from './localApi.mjs'

// Only a terminal receipt covering the requested target can confirm success.
export function validateToggleReceipt(data, expectedId, enabling) {
  const fail = () => { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.error) fail()
  const rows = enabling ? data.enabled_mods : data.disabled_mods
  const count = enabling ? data.enabled : data.disabled
  if (!Number.isSafeInteger(count) || count < 0 || !Array.isArray(rows)) fail()
  if (enabling ? (data.verified !== undefined && data.verified !== true) : data.verified !== true) fail()
  if (data.external_configs != null && (typeof data.external_configs !== 'object'
    || Array.isArray(data.external_configs) || data.external_configs.complete !== true)) fail()
  const ids = rows.map(row => {
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || !(typeof row.id === 'string' && row.id.trim() || Number.isSafeInteger(row.id) && row.id >= 0)) fail()
    return String(row.id)
  })
  if (new Set(ids).size !== ids.length) fail()
  if (!enabling && data.already_disabled === true && count === 0 && rows.length === 0) return data
  if (!ids.includes(String(expectedId))) fail()
  return data
}
