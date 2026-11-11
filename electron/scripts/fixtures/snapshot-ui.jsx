import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import SnapshotsPage from '../../src/components/SnapshotsPage'
const mode=new URLSearchParams(location.search).get('mode')
window.fixture={toasts:[],creates:0,writes:0,listReads:0}
const originalTimeout=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>originalTimeout(fn,[120000,15000].includes(ms)?150:ms,...args)
window.fetch=async(url,options={})=>{
  const json=data=>new Response(JSON.stringify(data))
  const hung=()=>new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
  if(mode?.startsWith('list-')){
    if(url.includes('/storage'))return json({})
    window.fixture.listReads++
    if(mode==='list-refresh'&&window.fixture.listReads===2)return new Response('{}',{status:503})
    if(mode==='list-empty')return json([])
    if(window.fixture.listReads===1){
      if(mode==='list-label-object')return json([{id:'broken',timestamp:1,files_count:1,trigger_mod_name:{text:'broken'}}])
      if(mode==='list-count-object')return json([{id:'broken',timestamp:1,files_count:{count:1}}])
      if(mode==='list-bool-string')return json([{id:'broken',timestamp:1,files_count:1,valid:'false'}])
      if(mode==='list-duplicate')return json([{id:'broken',timestamp:1,files_count:1},{id:'broken',timestamp:1,files_count:1}])
      if(mode==='list-http')return new Response('{}',{status:503})
      if(mode==='list-body')return hung()
      if(mode==='list-invalid')return json({})
      if(mode==='list-loading')return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json([]))})
    }
    return json([{id:'snap-recovered',timestamp:1,files_count:1}])
  }
  if(mode?.startsWith('restore-')||mode?.startsWith('delete-')){
    const sid='snap-fixture'
    if(url.endsWith('/preview')){
      if(mode==='restore-preview-invalid')return json({snapshot_id:sid})
      const receipt={snapshot_id:sid,confirmation_token:'fixture-token',to_delete:[],to_delete_count:0,to_restore_count:1}
      if(mode==='restore-preview-config-invalid')receipt.external_configs={action_count:'2'}
      if(mode==='restore-preview-workshop-invalid')receipt.workshop={to_unsubscribe:'123',to_resubscribe:[]}
      if(mode==='restore-preview-flag-invalid')receipt.domain_sniffed='false'
      if(mode==='restore-workshop-unavailable')receipt.workshop={preview_unavailable:true}
      if(mode==='restore-warnings')Object.assign(receipt,{baseline:true,domain_sniffed:true,external_configs:{action_count:2},missing_in_snapshot:['missing'],workshop:{to_unsubscribe:['one'],to_resubscribe:['two']}})
      if(mode==='restore-switch')return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json(receipt))})
      return json(receipt)
    }
    if(url.endsWith('/delete-preview')){
      if(mode==='delete-switch')return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json({snapshot_id:sid,confirmation_token:'fixture-token'}))})
      return json(mode==='delete-preview-invalid'?{}:{snapshot_id:sid,confirmation_token:'fixture-token'})
    }
    if(url.includes('/snapshot_restore')||options.method==='DELETE'){
      window.fixture.writes++
      if(mode.includes('-late-'))return new Promise((resolve,reject)=>{window.fixture.finish=()=>mode.endsWith('error')?reject(new Error('old game failure')):resolve(json(options.method==='DELETE'?{ok:true}:{result:JSON.stringify({complete:true,deleted:0,restored:1})}))})
      if(mode.endsWith('body'))return hung()
      if(mode.endsWith('http'))return new Response('{}',{status:503})
      if(mode==='restore-invalid'||mode==='delete-invalid')return json({})
      const receipt={snapshot_id:sid,complete:true,deleted:0,restored:1,unchanged_verified:0}
      if(mode==='restore-audit-pending')Object.assign(receipt,{complete:false,audit_log_saved:false,restore_verified:true})
      if(mode==='restore-inventory-pending')Object.assign(receipt,{complete:false,inventory_cleanup:{complete:false,failed_mod_ids:['fixture']}})
      if(mode==='restore-count-invalid')receipt.restored='1'
      if(mode==='restore-id-invalid')receipt.snapshot_id='other'
      if(mode==='restore-workshop-invalid')receipt.workshop={in_sync:'false',manual_subscribe:['one']}
      if(mode==='restore-workshop-valid')receipt.workshop={in_sync:false,manual_subscribe:['one'],manual_unsubscribe:[],unsubscribed:[],resubscribed:[]}
      return json(options.method==='DELETE'?{ok:true}:{result:JSON.stringify(receipt)})
    }
    return json(url.includes('/storage')?{}:[{id:sid,timestamp:1,files_count:1}])
  }
  if(url.includes('/snapshot_create')){
    window.fixture.creates++
    if(mode.startsWith('create-late-'))return new Promise((resolve,reject)=>{window.fixture.finish=()=>mode.endsWith('error')?reject(new Error('old game failure')):resolve(json({result:JSON.stringify({snapshot_id:'saved-fixture'})}))})
    if(mode==='http')return new Response('{}',{status:503})
    if(mode==='body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    return new Response(JSON.stringify(mode==='invalid'?{}:{result:JSON.stringify({snapshot_id:'saved-fixture'})}))
  }
  return new Response(JSON.stringify(url.includes('/storage')?{}:[]))
}
function Fixture(){
  const [game,setGame]=useState('fixture')
  window.fixture.switchGame=()=>setGame('otherfixture')
  return <><div data-game={game}/><SnapshotsPage api="http://fixture.invalid" language="en" status={{game_slug:game}} toast={text=>window.fixture.toasts.push(text)}/></>
}
createRoot(document.getElementById('root')).render(<Fixture/> )
