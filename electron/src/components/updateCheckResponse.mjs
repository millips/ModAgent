import {LocalApiError} from './localApi.mjs'

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const count = value => Number.isSafeInteger(value) && value >= 0
const optionalText = (item,key) => item[key] == null || typeof item[key] === 'string'

export function validateUpdateCheckResponse(data) {
  const fail = () => { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  if (!object(data) || data.error || (data.cancelled != null && typeof data.cancelled !== 'boolean')) fail()
  if (!object(data.summary) || !count(data.summary.total) || !Array.isArray(data.updates_available)) fail()
  if (['checked_nexus','checked_thunderstore'].some(key => data[key] != null && !count(data[key]))) fail()
  if (data.failed_checks != null && (!Array.isArray(data.failed_checks) || !data.failed_checks.every(object))) fail()
  if (data.items != null && !Array.isArray(data.items)) fail()
  const identities = new Set()
  for (const item of data.updates_available) {
    if (!object(item) || !(typeof item.mod_id === 'string' && item.mod_id.trim() || count(item.mod_id))
      || typeof item.latest !== 'string' || !item.latest.trim()
      || !['name','current','source','status'].every(key => optionalText(item,key))) fail()
    const id = String(item.mod_id)
    if (identities.has(id)) fail()
    identities.add(id)
  }
  return data
}
