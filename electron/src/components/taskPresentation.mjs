const terminalTypes = new Set(['task_completed', 'task_partial', 'task_failed', 'task_cancelled', 'decision_required'])

export function pendingPlanCard(messages, taskId) {
  if (!taskId) return null
  return messages.find(item => item.role === 'edition' && item.payload?.plan_task_id === taskId
    && item.payload?.phase === 'confirm' && item.payload?.items?.length > 0) || null
}

export function taskActionLabel(value, language) {
  const labels = {
    waiting_for_confirmation: ['等待你核对清单后确认', 'Waiting for you to review and confirm'],
    confirm_or_adjust_plan: ['查看待确认清单，或返回调整选择', 'Review the pending selection or adjust it'],
  }
  return labels[value]?.[language === 'en' ? 1 : 0] || value
}

export function updateTaskProgress(previous, progress, language, now, startedAt) {
  const prior = previous || { startedAt }
  const heartbeat = progress.stage === 'heartbeat'
  const label = language === 'en' && progress.label_en ? progress.label_en : progress.label
  return {
    ...prior,
    label: heartbeat && prior.label ? prior.label : label,
    stage: heartbeat ? prior.stage : progress.stage,
    stageStartedAt: heartbeat || (prior.stage === progress.stage) ? (prior.stageStartedAt || now) : now,
    waiting: heartbeat,
    mode: 'indeterminate', pct: 0, etaSeconds: null,
  }
}

export function upsertProgressMessage(messages, id, content, heartbeat = false) {
  const found = messages.some(item => item.id === id)
  if (!found) return [...messages, { id, role: 'sys', kind: 'progress', content }]
  return messages.map(item => item.id === id && !heartbeat ? { ...item, content } : item)
}

export function isTerminalTaskEvent(event) {
  return !!event?.task_id && terminalTypes.has(event.type)
}

// Live streaming and reconnect replay use this same terminal-event reducer.
export function upsertTaskResult(messages, event) {
  if (!isTerminalTaskEvent(event)) return messages
  const id = `task-result-${event.task_id}${event.run_id ? `-${event.run_id}` : ''}`
  const found = messages.findIndex(item => item.id === id)
  if (found >= 0 && Number(messages[found].event?.seq || 0) >= Number(event.seq || 0)) return messages
  const next = { id, role: 'task-result', event }
  return found < 0 ? [...messages, next] : messages.map((item, index) => index === found ? next : item)
}

const normalize = value => String(value || '').replace(/[*#`\s]/g, '')

export function taskPresentation(event, precedingAnswer = '') {
  const result = event?.payload?.result || {}
  const completed = Array.isArray(result.completed) ? result.completed.length : 0
  const pending = Array.isArray(result.not_completed) ? result.not_completed.length : 0
  const warnings = Array.isArray(result.warnings) ? result.warnings.length : 0
  const cleanSuccess = event?.state === 'COMPLETED' && !completed && !pending && !warnings
  const summary = normalize(result.summary).replace(/[…]+$/, '')
  const answer = normalize(precedingAnswer)
  // Older backends copied (and sometimes truncated) the whole answer into the card.
  const duplicate = !!summary && !!answer && (summary === answer || (summary.length >= 80 && answer.startsWith(summary)))
  const hidden = cleanSuccess && !!answer && (event?.payload?.presentation?.show_card === false || duplicate)
  return { hidden, summary: duplicate ? '' : result.summary || '', showCounts: event?.state !== 'WAITING_CONFIRMATION' && completed + pending > 0 }
}

export function precedingAnswer(messages, index) {
  const parts = []
  for (let n = index - 1; n >= 0; n--) {
    if (messages[n].role === 'user') break
    if (['agent', 'assistant'].includes(messages[n].role)) parts.unshift(messages[n].content || '')
  }
  return parts.join('\n')
}
