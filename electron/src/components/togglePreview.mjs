import {LocalApiError} from './localApi.mjs'

export function validateTogglePreview(data, expectedId, enabling) {
  const fail = () => { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  const object = v => v && typeof v === 'object' && !Array.isArray(v)
  const id = v => typeof v === 'string' && v.trim() || Number.isSafeInteger(v) && v >= 0
  const texts = (v, keys) => keys.every(k => v[k] === undefined || typeof v[k] === 'string')
  const rows = v => Array.isArray(v) && v.every(row => object(row) && id(row.id) && texts(row,['name']))
  if (!object(data) || data.error) fail()
  for (const key of ['blocked','requires_confirmation','requires_external_manager']) {
    if (data[key] !== undefined && typeof data[key] !== 'boolean') fail()
  }
  if (!object(data.target) || !id(data.target.id) || String(data.target.id) !== String(expectedId)) fail()
  if (!texts(data,['note','user_action','confirmation_token'])) fail()
  if (data.requires_external_manager === true) {
    if (data.blocked !== true) fail()
  } else if (data.action !== (enabling ? 'enable' : 'disable')) fail()
  if (data.blocked !== true && data.requires_confirmation !== true) fail()
  if (!enabling && data.blocked !== true && !data.confirmation_token?.trim()) fail()
  for (const key of ['dependencies','dependents','will_enable','will_disable','already_disabled']) {
    if (data[key] !== undefined && !rows(data[key])) fail()
  }
  if (data.missing_dependencies !== undefined && (!Array.isArray(data.missing_dependencies)
    || !data.missing_dependencies.every(v => typeof v === 'string'))) fail()
  if (data.decision_support !== undefined) {
    const d = data.decision_support
    if (!object(d) || !texts(d,['summary','why_this_step','recommendation','recovery'])) fail()
    for (const key of ['player_impact','already_inactive','retained']) {
      if (d[key] !== undefined && (!Array.isArray(d[key]) || !d[key].every(row => object(row)
        && texts(row,['name','role_label','functionality_lost'])))) fail()
    }
  }
  return data
}
