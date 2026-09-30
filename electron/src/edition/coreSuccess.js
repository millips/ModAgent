import { FEEDBACK_EVENT } from '../feedback/feedbackBus'

export const CORE_SUCCESS_EVENT = 'modagent:core-success'
const STORAGE_KEY = 'modagent-core-success-at'
const CORE_SUCCESS_TYPES = new Set([
  'scan-complete',
  'snapshot-complete',
  'rollback-complete',
  'install-complete',
  'install-batch-complete',
  'download-batch-complete',
])

export function readCoreSuccessAt() {
  try { return Number(localStorage.getItem(STORAGE_KEY) || 0) || 0 } catch (_) { return 0 }
}

export function hasCoreSuccess() {
  return readCoreSuccessAt() > 0
}

export function recordCoreSuccess(type) {
  if (!CORE_SUCCESS_TYPES.has(type) || hasCoreSuccess()) return false
  const completedAt = Date.now()
  try { localStorage.setItem(STORAGE_KEY, String(completedAt)) } catch (_) { return false }
  window.dispatchEvent(new CustomEvent(CORE_SUCCESS_EVENT, { detail: { completedAt, type } }))
  return true
}

export function installCoreSuccessTracking() {
  window.addEventListener(FEEDBACK_EVENT, event => recordCoreSuccess(event.detail?.type))
}
