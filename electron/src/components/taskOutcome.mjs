// Shared receipt decisions. Transport completion is not business completion.
export function canPresentConfirmation({ streamCompleted, streamFailed, executionFailed, planBlocked }) {
  return !!streamCompleted && !streamFailed && !executionFailed && !planBlocked
}

export function canCompleteSelection(state) {
  return canPresentConfirmation(state)
    && (state.selectionAction !== 'confirm' || state.executionVerified === true)
}

export function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail
  if (typeof detail === 'string' && detail) return detail
  if (typeof detail?.message === 'string' && detail.message) return detail.message
  return typeof payload?.message === 'string' && payload.message ? payload.message : fallback
}

export function receiptProgress(receipt, label, language) {
  const status = receipt?.outcome_status || receipt?.status || ''
  const waiting = ['waiting_user', 'manual_action_required', 'partial_manual_action_required',
    'preinstall_confirmation_required', 'variant_selection_required'].includes(status)
  const success = receipt?.ok === true && (!status || ['success', 'completed', 'downloaded',
    'installed', 'ready', 'already_installed', 'already_completed'].includes(status))
  if (waiting) return language === 'en' ? `${label}: waiting for your action` : `${label}：等待用户处理`
  if (!success) return language === 'en' ? `${label}: not completed; preparing a summary` : `${label}：未完成，正在整理结果`
  return language === 'en' ? `${label}: step completed; preparing results` : `${label}：此步骤完成，正在整理结果`
}
