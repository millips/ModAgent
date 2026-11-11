import React from 'react'
import { createRoot } from 'react-dom/client'
import ConnectionTestPanel from '../../src/components/ConnectionTestPanel'
import '../../src/index.css'

const targets = ['github', 'github_raw', 'nexus', 'thunderstore', 'modio', 'gamebanana', 'workshop'].map((id, i) => ({
  id, name: ['GitHub API', 'GitHub Raw', 'Nexus Mods', 'Thunderstore', 'mod.io', 'GameBanana', 'Steam Workshop'][i],
  url: 'https://example.com/' + id,
}))
const scenario = new URLSearchParams(window.location.search).get('scenario') || ''
window.fixture = { requests: [], active: 0, peak: 0, retry: false, aborts: 0 }
function stalledBody(signal) {
  return new Response(new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('{'))
    signal.addEventListener('abort', () => {
      window.fixture.aborts++
      controller.error(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  } }), { status: 200 })
}
window.fetch = async (url, options = {}) => {
  if (url.endsWith('/network/targets')) {
    if (!window.fixture.retry) {
      if (scenario === 'bad-url') return { ok: true, json: async () => ({ targets: [{...targets[0], url: 'broken'}] }) }
      if (scenario === 'duplicate-id') return { ok: true, json: async () => ({ targets: [targets[0], targets[0]] }) }
      if (scenario === 'http-failure') return { ok: false, status: 503 }
      if (scenario === 'stalled-list') return stalledBody(options.signal)
    }
    return { ok: true, json: async () => ({ targets }) }
  }
  const { target_id: id } = JSON.parse(options.body)
  const f = window.fixture
  f.requests.push(id)
  if (scenario === 'stalled-body' || scenario === 'unmount-body') return stalledBody(options.signal)
  if (scenario === 'bad-result') return { ok: true, json: async () => ({target_id: id, status: 'constructor'}) }
  f.active++
  f.peak = Math.max(f.peak, f.active)
  await new Promise(resolve => setTimeout(resolve, 90))
  f.active--
  if (id === 'workshop' && !f.retry) return { ok: false, status: 503 }
  const status = f.retry ? 'reachable' : ({ nexus: 'restricted', modio: 'timeout', gamebanana: 'redirect' }[id] || 'reachable')
  return { ok: true, status: 200, json: async () => ({
    target_id: id, status, elapsed_ms: 120, http_status: status === 'timeout' ? null : status === 'restricted' ? 403 : status === 'redirect' ? 302 : 200,
    checked_at: '2026-10-09T06:30:00Z',
  }) }
}
function App() {
  const [language, setLanguage] = React.useState('zh-CN')
  const [visible, setVisible] = React.useState(true)
  return <div className="p-6 max-w-2xl mx-auto">
    <button id="toggle" onClick={() => setVisible(v => !v)}>Toggle panel</button>
    <button id="language" className="btn-ghost mb-3" onClick={() => setLanguage(v => v === 'en' ? 'zh-CN' : 'en')}>中文 / English</button>
    {visible && <ConnectionTestPanel api="http://127.0.0.1:9999" language={language} />}
  </div>
}
createRoot(document.getElementById('root')).render(<App />)
