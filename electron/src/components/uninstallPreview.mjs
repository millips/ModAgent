import {LocalApiError} from './localApi.mjs'

export function validateUninstallPreview(preview, expectedId) {
  const count = value => Number.isSafeInteger(value) && value >= 0
  if (!preview || typeof preview !== 'object' || Array.isArray(preview)
    || preview.error || preview.requires_confirmation !== true
    || !['string','number'].includes(typeof preview.mod_id)
    || String(preview.mod_id) !== String(expectedId)
    || typeof preview.will_unsubscribe !== 'boolean'
    || !count(preview.will_delete_count) || !count(preview.blocked_unsafe_count)
    || !Array.isArray(preview.dependents) || !preview.dependents.every(name => typeof name === 'string')
    || (preview.will_unsubscribe && preview.will_delete_count !== 0)) {
    throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  }
  return preview
}
