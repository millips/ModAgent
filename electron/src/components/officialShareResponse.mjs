import {LocalApiError} from './localApi.mjs'
import {validateSharePreview} from './shareResponse.mjs'
const invalid = () => { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
export function validateOfficialPreview(result, expectedId) {
  validateSharePreview(result)
  if (result.source_kind !== 'official_collection' || result.official?.id !== expectedId) invalid()
  return result
}
export function validateOfficialCatalog(result) {
  if (typeof result?.available !== 'boolean' || typeof result.fetched !== 'boolean'
      || typeof result.source !== 'string' || !Array.isArray(result.collections)) invalid()
  if (result.cache_age_seconds != null && (!Number.isFinite(result.cache_age_seconds) || result.cache_age_seconds < 0)) invalid()
  for (const item of result.collections) {
    if (!item || typeof item.id !== 'string' || !item.id
        || !Number.isInteger(item.mod_count) || item.mod_count < 0) invalid()
    for (const field of ['title','description']) if (item[field] !== undefined && typeof item[field] !== 'string') invalid()
    if (item.warnings !== undefined && (!Array.isArray(item.warnings) || item.warnings.some(w=>typeof w!=='string'))) invalid()
  }
  return result
}
export function validateOfficialDiagnostics(result) {
  if (!Array.isArray(result?.checks) || typeof result.cache_available !== 'boolean') invalid()
  if (result.checks.some(c=>!c || typeof c.ok !== 'boolean' || typeof c.endpoint !== 'string' || !c.endpoint)) invalid()
  return result
}
