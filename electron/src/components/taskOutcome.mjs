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

export function cancellationFeedback(result, language) {
  const en = language === 'en'
  if (result?.ok !== true) return { level: 'warn', message: en
    ? '[TASK_CANCEL_UNCONFIRMED] Display stopped, but cancellation was not confirmed. Check the task state before retrying.'
    : '[TASK_CANCEL_UNCONFIRMED] 界面已停止，但后台未确认取消。请先检查任务状态，不要立即重复操作。' }
  if (result.chat_cancelled === true) return { level: 'success', message: en
    ? '[TASK_TURN_INVALIDATED] The backend invalidated this turn. Completed changes were not rolled back; review the task record.'
    : '[TASK_TURN_INVALIDATED] 后台已使本轮失效。已完成的修改不会自动撤销，请核对任务记录。' }
  return { level: 'warn', message: en
    ? '[TASK_CANCEL_REQUESTED] Cancellation requested; the current step may still be finishing. Check its final state before retrying.'
    : '[TASK_CANCEL_REQUESTED] 已请求取消，当前步骤可能仍在收尾。请确认最终状态后再重试。' }
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
