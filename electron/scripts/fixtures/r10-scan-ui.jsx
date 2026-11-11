import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import ChatPage from '../../src/components/ChatPage.jsx'
window.fixture = { calls: [], toasts: [], refreshes: 0 }
window.modagent = {selectModDirectory:async()=>({path:'X:/FixtureMods'}),
  selectGameDirectory:async()=>{
    window.fixture.pickerCalls=(window.fixture.pickerCalls||0)+1
    if(window.fixture.pickerMode==='reject')throw Error('PRIVATE_FIXTURE')
    if(window.fixture.pickerMode==='cancel')return null
    if(window.fixture.pickerMode==='hang')return new Promise(resolve=>{window.releasePicker=resolve})
    return {path:'X:/FixtureGame',suggestedName:'Fixture Game'}
  }}
window.fetch = async (url, options = {}) => {
  window.fixture.calls.push(String(url))
  if(String(url).endsWith('/mods/import-directory'))return {ok:true,json:async()=>({
    game_instance_id:'fixture',directories:['X:/FixtureMods'],status:'running',queued:true,
    ...window.fixture.saveResult})}
  if(String(url).includes('/mods/scan-status?'))return {ok:true,json:async()=>({
    game_instance_id:'fixture',...window.fixture.backgroundResult})}
  if(window.fixture.hang && String(url).endsWith('/tool/scan_existing_mods'))return new Response(new ReadableStream({start(c){
    options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')),{once:true})
  }}))
  const data = String(url).includes('/sessions') ? []
    : String(url).endsWith('/tool/scan_existing_mods')
      ? { result: JSON.stringify(window.fixture.scanResult || { identified: [], imported: 0, detected: 129 }) } : {}
  return { ok: true, json: async () => data }
}
function Fixture() {
  const [count, setCount] = useState(0)
  const [language,setLanguage]=useState('zh-CN')
  window.fixture.setLanguage=setLanguage
  return <><output id="inventory-count">{count}</output><ChatPage api="https://fixture.invalid" games={[]} language={language}
    status={{ online: true, game_slug: 'fixture', game_name: 'Fixture', installed_mods: count }}
    toast={(message)=>window.fixture.toasts.push(message)}
    onGameImport={async payload=>{
      window.fixture.importCalls=(window.fixture.importCalls||0)+1
      window.fixture.importPayload=payload
      if(window.fixture.holdImport)await new Promise(resolve=>{window.releaseImport=resolve})
      if(window.fixture.importRejected)throw new Error('[GAME_IMPORT_REJECTED] Fixture rejection')
      return {saved:true,game:{name:payload.game_name,game_instance_id:'fixture'},mod_scan:window.fixture.importScan}
    }}
    onRefresh={()=>{window.fixture.refreshes++; setCount(97)}} /></>
}
createRoot(document.getElementById('root')).render(<Fixture />)
