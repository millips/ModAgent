// Validate before React rendering or emitting any success/cancellation feedback.
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const optionalText = (value, key) => value[key] == null || typeof value[key] === 'string'
const optionalNumber = (value, key) => value[key] == null || (typeof value[key] === 'number' && Number.isFinite(value[key]))

export function validateDownloadStatus(value) {
  const valid = record(value)
    && typeof value.active === 'boolean'
    && Number.isSafeInteger(value.generation) && value.generation >= 0
    && typeof value.updated === 'number' && Number.isFinite(value.updated) && value.updated >= 0
    && typeof value.overall_pct === 'number' && Number.isFinite(value.overall_pct)
    && (value.cancel_requested == null || typeof value.cancel_requested === 'boolean')
    && ['task_kind', 'label', 'cancel_reason'].every(key => optionalText(value, key))
    && ['elapsed_seconds', 'eta_seconds'].every(key => optionalNumber(value, key))
    && (value.current_item == null || (record(value.current_item) && optionalText(value.current_item, 'phase')))
    && Array.isArray(value.items)
    && value.items.every(item => record(item)
      && typeof item.status === 'string' && item.status.length > 0
      && (item.mod_id == null || typeof item.mod_id === 'string' || (typeof item.mod_id === 'number' && Number.isFinite(item.mod_id)))
      && ['name', 'source', 'source_label', 'phase', 'phase_label', 'detail', 'error'].every(key => optionalText(item, key))
      && optionalNumber(item, 'pct'))
  if (!valid) throw new Error('DOWNLOAD_STATUS_INVALID')
  return value
}

export function progressPercent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
}
