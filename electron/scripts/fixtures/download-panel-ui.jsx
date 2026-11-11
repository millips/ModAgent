import React, {useState} from 'react'
import { createRoot } from 'react-dom/client'
import DownloadPanel from '../../src/components/DownloadPanel.jsx'

const originalTimeout = window.setTimeout.bind(window)
window.setTimeout = (fn, ms, ...args) => originalTimeout(fn, ms === 15000 ? 120 : ms === 800 ? 30 : ms, ...args)
const item = {mod_id: 1, name: 'Fixture', status: 'downloading', phase: 'transferring', pct: 25}
window.fixture = {
  state: {active: true, task_kind: 'download', generation: 1, items: [item, {...item, mod_id: 2}], updated: Date.now()/1000, overall_pct: 25},
  polls: 0, concurrent: 0, maxConcurrent: 0, cancels: 0, events: [], mode: 'valid',
}
window.addEventListener('modagent:feedback', event => window.fixture.events.push(event.detail.type))
window.fetch = async (url, options = {}) => {
  const f = window.fixture
  if (url.endsWith('/tasks/cancel')) {
    f.cancels++
    f.body = JSON.parse(options.body)
    if (f.mode === 'timeout') await new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('private fixture error')), {once:true}))
    await new Promise(resolve => originalTimeout(resolve, 70))
    return {ok: f.mode !== 'http', status: 500, json: async () => ({ok: f.mode !== 'reject'})}
  }
  f.polls++; f.concurrent++; f.maxConcurrent = Math.max(f.maxConcurrent, f.concurrent)
  if (f.mode === 'poll-timeout') {
    try { await new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('fixture timeout')), {once:true})) }
    finally { f.concurrent-- }
  }
  await new Promise(resolve => originalTimeout(resolve, 45))
  f.concurrent--
  if (f.mode === 'poll-error') throw new Error('private fixture error')
  if (f.mode.startsWith('malformed-')) {
    const state = structuredClone(f.state)
    if (f.mode === 'malformed-detail') state.items[0].detail = {message:'private malformed detail'}
    if (f.mode === 'malformed-phase') state.items[0].phase_label = {message:'private malformed phase'}
    if (f.mode === 'malformed-cancel') state.cancel_requested = 'false'
    if (f.mode === 'malformed-number') state.overall_pct = 'not a number'
    return {ok:true,json:async()=>state}
  }
  return {ok: true, json: async () => f.mode === 'invalid' ? {items: []} : structuredClone(f.state)}
}
function Fixture() {
  const [language, setLanguage] = useState(new URLSearchParams(location.search).get('language') || 'zh-CN')
  window.fixture.setLanguage = setLanguage
  return <DownloadPanel api="http://fixture" language={language} />
}
createRoot(document.getElementById('root')).render(<Fixture />)
