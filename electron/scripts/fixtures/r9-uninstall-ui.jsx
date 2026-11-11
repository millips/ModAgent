import React, {useState} from 'react'
import { createRoot } from 'react-dom/client'
import ModsPage from '../../src/components/ModsPage.jsx'

window.fixture = { scenario: new URLSearchParams(location.search).get('scenario') || 'partial', calls: [], toasts: [], feedback: [], removedIds: [] }
const originalTimer=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>originalTimer(fn,[15000,120000].includes(ms)?150:ms,...args)
window.addEventListener('modagent:feedback', event => window.fixture.feedback.push(event.detail))
window.fetch = async (url, init = {}) => {
  const f = window.fixture
  const args = JSON.parse(init.body || '{}')
  f.calls.push({ url: String(url), args })
  let data = {}
  if (String(url).includes('/mods?')) {
    data = [{ id: 'fixture', name: 'Fixture Mod', localized_name: 'Fixture Mod',
      summary: 'Synthetic data, no real game files', summary_evidence: 'fixture', version: '1' }]
    if (f.scenario.startsWith('batch')) data.push({ ...data[0], id: 'failed', name: 'Failed Mod', localized_name: 'Failed Mod' })
    data = data.filter(row => !f.removedIds.includes(row.id))
  } else if (String(url).endsWith('/tool/snapshot_create')) {
    if(f.scenario==='batch-switch')return new Promise(resolve=>{f.resolve=()=>resolve({ok:true,json:async()=>({result:JSON.stringify({snapshot_id:'old-snapshot'})})})})
    if(f.scenario==='batch-snapshot-invalid')return {ok:true,json:async()=>({})}
    data = { result: JSON.stringify({ snapshot_id: 'fixture-snapshot' }) }
  } else if (String(url).endsWith('/tool/mod_uninstall')) {
    if(f.scenario==='batch-body'&&args.confirmed)return new Response(new ReadableStream({start(c){init.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    let receipt
    if (!args.confirmed) {
      receipt = f.scenario === 'preview-failed' ? { error: 'fixture preview unavailable' }
        : { requires_confirmation: true, mod_id:args.mod_id, will_unsubscribe:false, will_delete_count: 2, blocked_unsafe_count:0, dependents: [] }
      if(f.scenario==='workshop-preview')receipt={...receipt,will_unsubscribe:true,will_delete_count:0}
      if(f.scenario==='unsafe-preview')receipt={...receipt,blocked_unsafe_count:1,dependents:['Dependent Mod']}
      if(!f.scenario.startsWith('batch-')||args.mod_id==='failed'){
        if(f.scenario.endsWith('invalid-count'))receipt.will_delete_count='2'
        if(f.scenario.endsWith('invalid-id'))receipt.mod_id='another-mod'
        if(f.scenario.endsWith('invalid-kind'))receipt.will_unsubscribe='false'
        if(f.scenario.endsWith('invalid-dependencies'))receipt.dependents={name:'Malformed'}
      }
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
function Fixture(){
  const [game,setGame]=useState('fixture')
  window.fixture.switchGame=()=>setGame('newfixture')
  return <><div data-game={game}/><ModsPage api="https://fixture.invalid"
  toast={(message, type) => window.fixture.toasts.push({ message, type })}
  status={{ game_slug: game }} language={new URLSearchParams(location.search).get('language')||'zh-CN'} /></>
}
createRoot(document.getElementById('root')).render(<Fixture/> )
