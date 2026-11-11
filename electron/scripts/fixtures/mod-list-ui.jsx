import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import ModsPage from '../../src/components/ModsPage'
const mode=new URLSearchParams(location.search).get('mode')
const originalTimer=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>originalTimer(fn,[120000,15000,30000].includes(ms)?150:ms,...args)
window.fixture={toasts:[],reconciles:0}
window.fetch=async(url,options={})=>{
  const json=data=>new Response(JSON.stringify(data))
  const hang=()=>new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
  if(/\/(dropbox|downloads|tools)\/open$/.test(url)){
    window.fixture.folderCalls=(window.fixture.folderCalls||0)+1
    if(window.fixture.folderMode==='body')return hang()
    if(window.fixture.folderMode==='http')return new Response('PRIVATE_FIXTURE',{status:503})
    if(window.fixture.folderMode==='false')return json({ok:false,error:'PRIVATE_FIXTURE'})
    if(window.fixture.folderMode==='invalid')return json({ok:'true',path:'PRIVATE_FIXTURE'})
    return json({ok:true,path:'X:/Fixture'})
  }
  if(url.endsWith('/package-merge')){
    window.fixture.merges=(window.fixture.merges||0)+1
    if(mode==='merge-body')return hang()
    if(mode==='merge-http')return new Response('{}',{status:503})
    const receipt={ok:true,name:'Test package',file_count:2}
    if(mode==='merge-switch')return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json(receipt))})
    return json(mode==='merge-invalid'?{}:receipt)
  }
  if(url.endsWith('/mod_source_bind')){
    const args=JSON.parse(options.body)
    ;(window.fixture.bindArgs??=[]).push(args)
    if(!window.fixture.sourceRecovered&&mode==='source-body')return hang()
    if(!window.fixture.sourceRecovered&&mode==='source-http')return new Response('{}',{status:503})
    const preview={local:{mod_id:args.local_mod_id},nexus:{mod_id:Number(args.source_key),name:'Verified source',version:'1'}}
    const result=args.confirmed?{bound:true,source:args.source,source_key:args.source_key,preview}:{requires_confirmation:true,preview}
    if(args.confirmed&&mode==='source-confirm-hold')return new Promise(resolve=>{window.releaseSourceConfirm=()=>resolve(json({result:JSON.stringify(result)}))})
    if(args.confirmed&&mode==='source-confirm-invalid'&&!window.fixture.sourceRecovered)result.bound='true'
    if(!window.fixture.sourceRecovered&&mode==='source-invalid-flag')result.requires_confirmation='true'
    if(!window.fixture.sourceRecovered&&mode==='source-invalid-id')preview.local.mod_id='other'
    if(!window.fixture.sourceRecovered&&mode==='source-invalid-name')preview.nexus.name={unsafe:true}
    if(!window.fixture.sourceRecovered&&mode==='source-invalid-target')preview.nexus.mod_id=999
    return json({result:JSON.stringify(result)})
  }
  if(url.endsWith('/mod_disable')||url.endsWith('/mod_enable')){
    window.fixture.toggles=(window.fixture.toggles||0)+1
    if(mode==='toggle-body')return hang()
    if(mode==='toggle-http')return new Response('{}',{status:503})
    const badReceipts={
      'toggle-preview-id':{requires_confirmation:true,action:'disable',target:{id:'other'},confirmation_token:'token'},
      'toggle-preview-note':{requires_confirmation:true,action:'disable',target:{id:'same-id'},confirmation_token:'token',note:{}},
      'toggle-preview-external':{requires_external_manager:true,target:{id:'same-id'}},
      'toggle-preview-flags':{requires_confirmation:'true',blocked:'false',action:'disable',target:{id:'same-id'},confirmation_token:'token'},
      'toggle-empty':{verified:true,disabled:0,disabled_mods:[]},
      'toggle-wrong-id':{verified:true,disabled:1,disabled_mods:[{id:'other'}]},
      'toggle-external-incomplete':{verified:true,disabled:1,disabled_mods:[{id:'same-id'}],external_configs:{complete:false}},
      'toggle-duplicate':{verified:true,disabled:2,disabled_mods:[{id:'same-id'},{id:'same-id'}]},
    }
    if(badReceipts[mode])return json({result:JSON.stringify(badReceipts[mode])})
    if(mode.startsWith('dependency-')){
      const args=JSON.parse(options.body)
      ;(window.fixture.toggleArgs??=[]).push(args)
      if(!args.confirmed)return json({result:JSON.stringify(mode==='dependency-missing'
        ?{blocked:true,action:'enable',target:{id:'same-id'},missing_dependencies:['Required library'],note:'Install missing dependency'}
        :{requires_confirmation:true,action:'enable',target:{id:'same-id'},dependencies:[{id:'dependency',name:'Required library'}],note:'Dependencies first'})})
      if(mode==='dependency-body')return hang()
      if(mode==='dependency-switch-error')return new Promise((_resolve,reject)=>{window.fixture.rejectToggle=()=>reject(new Error('Old game failure'))})
      return json({result:JSON.stringify({enabled:2,enabled_mods:[{id:'dependency'},{id:'same-id'}],external_configs:{complete:true}})})
    }
    if(mode==='gate-valid'||mode==='gate-blocked'){
      const args=JSON.parse(options.body)
      if(!args.confirmed)return json({result:JSON.stringify(mode==='gate-blocked'
        ?{blocked:true,requires_external_manager:true,target:{id:'same-id'},note:'Use Steam'}
        :{requires_confirmation:true,action:'disable',target:{id:'same-id'},confirmation_token:'fixture-token',dependents:[{id:'dependent',name:'Dependent'}],note:'Preview only'})})
      window.fixture.toggleConfirmed=args
    }
    return json({result:JSON.stringify(mode==='toggle-invalid'?{}:mode==='enable-valid'?{enabled:1,enabled_mods:[{id:'same-id'}],details:[]}:{verified:true,disabled:1,disabled_mods:[{id:'same-id'}]})})
  }
  if(url.endsWith('/download_from_url'))return json({result:JSON.stringify(mode==='direct-invalid'?{}:{local_path:'fixture.zip',name:'Fixture'})})
  if(url.endsWith('/conflict_check'))return json({result:JSON.stringify({safe_to_install:true,incoming_files_count:1,conflicts:[],archive_contents:['fixture.dll'],planned_files:['Mods/fixture.dll']})})
  if(url.endsWith('/mod_install')){
    window.fixture.installs=(window.fixture.installs||0)+1
    const args=JSON.parse(options.body)
    ;(window.fixture.installArgs??=[]).push(args)
    if(mode==='direct-risk'&&!args.compatibility_confirmed)return json({result:JSON.stringify({requires_confirmation:true,compatibility_confirmation_required:true,install_blocked:false,message:'Fixture compatibility risk'})})
    if(mode==='direct-body')return hang()
    if(mode==='direct-cache')return json({result:JSON.stringify({files_installed:['Mods/fixture.dll'],snapshot_id:'snap',cache_cleanup:{status:'unconfirmed',warning:'PRIVATE'}})})
    return json({result:JSON.stringify(mode==='direct-blocked'?{status:'missing_dependencies',install_blocked:true}:{files_installed:['Mods/fixture.dll'],snapshot_id:'snap'})})
  }
  if(url.endsWith('/tool/mod_update')){
    window.fixture.writes=(window.fixture.writes||0)+1
    if(mode==='write-tls')return json({result:JSON.stringify({error:'PRIVATE',error_code:'UPDATE_SOURCE_FAILED',failure_kind:'tls_error',write_performed:false})})
    if(mode==='write-snapshot')return json({result:JSON.stringify({error:'PRIVATE',error_code:'UPDATE_SNAPSHOT_FAILED',snapshot_unconfirmed:true,write_performed:false})})
    if(mode==='write-cache')return json({result:JSON.stringify({updated:'Old Mod',version:'2',snapshot_id:'fixture-snap',warning_code:'UPDATE_CACHE_CLEANUP_UNCONFIRMED',warning:'PRIVATE'})})
    if(mode.startsWith('batch-')){
      (window.fixture.ids??=[]).push(JSON.parse(options.body).mod_id)
      const receipt={result:JSON.stringify({updated:'Batch Mod',version:'2',snapshot_id:'fixture-snap'})}
      if(mode==='batch-switch')return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json(receipt))})
      if(window.fixture.writes===2&&mode==='batch-hang')return hang()
      if(window.fixture.writes===2&&mode==='batch-failure')return json({result:JSON.stringify({error:'fixture',restored_previous:true})})
      return json(receipt)
    }
    if(mode==='write-body')return hang()
    return json({result:JSON.stringify(mode==='write-invalid'?{}:mode==='write-rollback'?{error:'fixture',restored_previous:false}:{updated:'Old Mod',version:'2',snapshot_id:'fixture-snap'})})
  }
  if(url.includes('/mod_update_check')||url.includes('/mod_source_align')){
    if(mode.startsWith('source-'))return json({result:JSON.stringify({attempted:1,summary:{unmatched:1},ambiguous:[],unmatched:[{mod_id:'same-id',name:'Old Mod'}]})})
    if(mode.startsWith('cancel-')||(!mode.startsWith('write-')&&mode.endsWith('body')))return hang()
    if(mode.endsWith('http'))return new Response('{}',{status:503})
    const result=mode.startsWith('align-')?{summary:{bound:0,unmatched:0},attempted:1,ambiguous:[],unmatched:[]}
      :{updates_available:[],summary:{total:1},checked_nexus:0,checked_thunderstore:0}
    if(mode.startsWith('write-'))result.updates_available=[{mod_id:'same-id',name:'Old Mod',latest:'2'}]
    if(mode.startsWith('batch-'))result.updates_available=['a','b','c'].map(mod_id=>({mod_id,name:'Batch '+mod_id,latest:'2'}))
    if(mode==='update-partial'){result.checked_nexus=1;result.failed_checks=[{name:'Unavailable Mod'}]}
    if(mode==='update-current')result.checked_nexus=1
    if(mode==='update-name-object')result.updates_available=[{mod_id:'same-id',name:{private:'malformed'},latest:'2'}]
    if(mode==='update-duplicate')result.updates_available=[{mod_id:'same-id',name:'Old Mod',latest:'2'},{mod_id:'same-id',name:'Old Mod',latest:'2'}]
    if(mode==='update-count-string')result.checked_nexus='1'
    if(mode==='update-cancel-string')result.cancelled='false'
    return json(!mode.startsWith('write-')&&mode.endsWith('invalid')?{}:{result:JSON.stringify(result)})
  }
  if(url.includes('/tasks/cancel')){
    if(mode==='cancel-body')return hang()
    if(mode==='cancel-http')return new Response('{}',{status:503})
    return json({ok:mode==='cancel-valid'})
  }
  if(url.includes('/reconcile')){
    window.fixture.reconciles++
    if(mode==='reconcile-body')return hang()
    return json(mode==='reconcile-invalid'?{}:{checked:1,issues:[],duplicates_merged:0})
  }
  if(url.includes('/mods?')){
    if(mode==='list-body')return hang()
    if(mode==='list-http')return new Response('{}',{status:503})
    if(mode==='list-invalid')return json([null])
    const old=url.includes('oldgame')
    const rows=[{id:'same-id',name:old?'Old Mod':'New Mod',localized_name:old?'Old Mod':'New Mod',summary:'Fixture',summary_evidence:'fixture'}]
    if(mode.startsWith('merge-'))rows.push({...rows[0],id:'second-id',name:'Second Mod',localized_name:'Second Mod'})
    if(mode==='enable-valid'||mode.startsWith('dependency-'))rows[0].disabled=true
    if(mode==='list-switch'&&old)return new Promise(resolve=>{window.fixture.resolve=()=>resolve(json(rows))})
    return json(rows)
  }
  return json({})
}
function Fixture(){
  const [game,setGame]=useState('oldgame')
  const [language,setLanguage]=useState('en')
  window.fixture.setLanguage=setLanguage
  window.fixture.switchGame=()=>setGame('newgame')
  return <ModsPage api="http://fixture.invalid" language={language} status={{game_slug:game}} toast={text=>window.fixture.toasts.push(text)}/>
}
createRoot(document.getElementById('root')).render(<Fixture/> )
