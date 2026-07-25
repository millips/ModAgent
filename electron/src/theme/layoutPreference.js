const STORAGE_KEY = 'modagent-layout-mode'
const DEFAULT_LAYOUT = 'plain'
const VALID_LAYOUTS = new Set(['plain', 'designed'])

export function readLayoutPreference() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return VALID_LAYOUTS.has(stored) ? stored : DEFAULT_LAYOUT
  } catch (_) {
    return DEFAULT_LAYOUT
  }
}

export function applyLayoutPreference(layout) {
  const next = VALID_LAYOUTS.has(layout) ? layout : DEFAULT_LAYOUT
  document.body.dataset.maLayout = next
  return next
}

export function saveLayoutPreference(layout) {
  const next = applyLayoutPreference(layout)
  try { localStorage.setItem(STORAGE_KEY, next) } catch (_) {}
  return next
}
