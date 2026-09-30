import React from 'react'
import { createRoot } from 'react-dom/client'
import ModsPage from '../../src/components/ModsPage.jsx'

window.fixture = { scenario: new URLSearchParams(location.search).get('scenario') || 'partial', calls: [], toasts: [], feedback: [], removedIds: [] }
window.addEventListener('modagent:feedback', event => window.fixture.feedback.push(event.detail))
window.fetch = async (url, init = {}) => {
  const f = window.fixture
  const args = JSON.parse(init.body || '{}')
  f.calls.push({ url: String(url), args })
  let data = {}
  if (String(url).includes('/mods?')) {
    data = [{ id: 'fixture', name: 'Fixture Mod', localized_name: 'Fixture Mod',
      summary: 'Synthetic data, no real game files', summary_evidence: 'fixture', version: '1' }]
    if (f.scenario === 'batch') data.push({ ...data[0], id: 'failed', name: 'Failed Mod', localized_name: 'Failed Mod' })
    data = data.filter(row => !f.removedIds.includes(row.id))
  } else if (String(url).endsWith('/tool/snapshot_create')) {
    data = { result: JSON.stringify({ snapshot_id: 'fixture-snapshot' }) }
  } else if (String(url).endsWith('/tool/mod_uninstall')) {
    let receipt
    if (!args.confirmed) {
      receipt = f.scenario === 'preview-failed' ? { error: 'fixture preview unavailable' }
        : { requires_confirmation: true, will_delete_count: 2, dependents: [] }
    } else if (f.scenario === 'success' || (f.scenario === 'batch' && args.mod_id === 'fixture')) {
      f.removedIds.push(args.mod_id)
      receipt = { status: 'completed', removed: 2, record_retained: false }
    } else {
      receipt = { status: 'partial', removed: 1, record_retained: true,
        message: 'fixture locked file; record retained', details: { errors: ['locked'] } }
    }
    data = { result: JSON.stringify(receipt) }
  }
  return { ok: true, status: 200, json: async () => data }
}
createRoot(document.getElementById('root')).render(<ModsPage api="https://fixture.invalid"
  toast={(message, type) => window.fixture.toasts.push({ message, type })}
  status={{ game_slug: 'fixture' }} />)
