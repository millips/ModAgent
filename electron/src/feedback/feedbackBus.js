export const FEEDBACK_EVENT = 'modagent:feedback'

export function emitFeedback(type, detail = {}) {
  if (!type || typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(FEEDBACK_EVENT, {
    detail: { ...detail, type, emittedAt: Date.now() },
  }))
}

const TOOL_FEEDBACK = {
  mod_install: 'install-complete',
  mod_install_custom: 'install-complete',
  mod_update: 'install-complete',
  mod_install_batch: 'install-batch-complete',
  mod_uninstall: 'remove-complete',
  mod_enable: 'enable',
  mod_disable: 'disable',
  workshop_install: 'install-complete',
  workshop_uninstall: 'remove-complete',
  mod_patch: 'success',
  mod_dependency_set: 'success',
  snapshot_create: 'snapshot-complete',
  snapshot_restore: 'rollback-complete',
  snapshot_delete: 'remove-complete',
  scan_existing_mods: 'scan-complete',
  import_existing_mods: 'scan-complete',
}

const INSTALL_START_TOOLS = new Set([
  'mod_install', 'mod_install_custom', 'mod_update',
  'mod_install_batch', 'workshop_install',
])

export function emitToolStartFeedback(name, detail = {}) {
  if (INSTALL_START_TOOLS.has(name)) {
    emitFeedback('install-start', { ...detail, tool: name })
  }
}

export function emitToolFeedback(name, ok, detail = {}) {
  if (!ok) {
    emitFeedback('error', { ...detail, tool: name })
    return
  }
  const type = TOOL_FEEDBACK[name]
  if (!type) return

  const previewText = String(detail.preview || '')
  if (/"requires_confirmation"\s*:\s*true/.test(previewText)) {
    emitFeedback('notice', { ...detail, tool: name, gate: true })
    return
  }
  if (/"blocked"\s*:\s*true/.test(previewText)) {
    emitFeedback('warning', { ...detail, tool: name, blocked: true })
    return
  }
  if (name === 'snapshot_restore' && !/"complete"\s*:\s*true/.test(previewText)) {
    emitFeedback('warning', { ...detail, tool: name, incomplete: true })
    return
  }

  let count = Number(detail.count) || 0
  if (name === 'mod_install_batch' && !count) {
    const preview = String(detail.preview || '')
    const succeeded = preview.match(/"succeeded"\s*:\s*(\d+)/)
    const failed = preview.match(/"failed"\s*:\s*(\d+)/)
    const total = preview.match(/"total"\s*:\s*(\d+)/)
    const succeededCount = succeeded ? Number(succeeded[1]) : null
    const failedCount = failed ? Number(failed[1]) : 0
    if (succeededCount === 0 && failedCount > 0) {
      emitFeedback('error', { ...detail, tool: name, failed: failedCount })
      return
    }
    count = succeededCount ?? Number(total?.[1] || 1)
    detail = { ...detail, failed: failedCount }
  }
  emitFeedback(type, { ...detail, ...(count ? { count } : {}), tool: name })
}
