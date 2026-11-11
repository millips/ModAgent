import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import SettingsPage from '../../src/components/SettingsPage'
const mode=new URLSearchParams(location.search).get('mode')
window.fixture={stores:0,requests:[],toasts:[],statusReads:0,plans:[],saves:[]}
const timer=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>timer(fn,[15000,20000,30000].includes(ms)?150:ms,...args)
window.modagent={exportRuntimeDiagnostics:async language=>{
  window.fixture.diagnosticCalls=(window.fixture.diagnosticCalls||0)+1
  window.fixture.diagnosticLanguage=language
  await new Promise(resolve=>setTimeout(resolve,30))
  if(mode==='report-cancel')return {cancelled:true}
  if(mode==='report-error')throw new Error('private path must not leak')
  if(mode==='report-invalid')return 'old-unverified-path'
  return {ok:true,filename:'fixture.txt'}
},saveShareFile:async payload=>{
  window.fixture.saves.push(payload)
  if(mode==='export-cancel')return {cancelled:true}
  if(mode==='export-disk')return {ok:false,error:'SHARE_SAVE_FAILED'}
  return {ok:true,filename:'fixture.json'}
},saveSecrets:async()=>{
  window.fixture.stores++
  if(mode==='credential-error')return {ok:false,error:'credential_encryption_unavailable'}
  if(mode==='credential-timeout')return new Promise(()=>{})
  return {ok:true,llm_set:true}
}}
if(mode.startsWith('maintenance-')&&mode!=='maintenance-missing'){
  const operation=async()=>{
    window.fixture.maintenanceCalls=(window.fixture.maintenanceCalls||0)+1
    if(mode==='maintenance-timeout')return new Promise(()=>{})
    await new Promise(resolve=>setTimeout(resolve,40))
    if(mode==='maintenance-open-error')return 'private folder error'
    return mode==='maintenance-copy'?{ok:true}:''
  }
  window.modagent.openDiagnosticsFolder=operation
  window.modagent.copyMaintenancePath=operation
}
if(mode.startsWith('background-')){
  window.modagent.getBgDataUrl=async name=>mode==='background-preview-invalid'&&name==='new.png'?null:'data:image/png;base64,fixture'
  window.modagent.selectBg=async()=>{
    window.fixture.backgroundCalls=(window.fixture.backgroundCalls||0)+1
    await new Promise(resolve=>setTimeout(resolve,40))
    if(mode==='background-error')throw Error('private source path')
    return 'new.png'
  }
  window.modagent.removeBg=async()=>{
    window.fixture.backgroundCalls=(window.fixture.backgroundCalls||0)+1
    await new Promise(resolve=>setTimeout(resolve,40))
    return {ok:true}
  }
}
if(mode.startsWith('update-'))window.modagent.checkForAppUpdate=async()=>{
  window.fixture.updateCalls=(window.fixture.updateCalls||0)+1
  if(mode==='update-timeout')return new Promise(()=>{})
  await new Promise(resolve=>setTimeout(resolve,40))
  if(mode==='update-disabled')return {ok:true,disabled:true,available:false}
  if(mode==='update-invalid')return {ok:true,version:'1.7.0'}
  return {ok:true,available:mode==='update-available',version:'1.7.0'}
}
window.fetch=async(url,options={})=>{
  window.fixture.requests.push({url,body:options.body})
  if(url.endsWith('/tool/official_share_import')){
    const empty=mode==='official-empty'
    const result={source_kind:'official_collection',official:{id:mode==='official-mismatch'?'ma-other':'ma-fixture'},items:empty?[]:[{name:'Fixture'}],summary:{total:empty?0:1,host_dependency_requirements:mode==='official-prerequisite'?[{name:'Loader',status:'needs_external_resolution'}]:[]}}
    return new Response(JSON.stringify({result:JSON.stringify(result)}))
  }
  if(url.endsWith('/tool/official_share_catalog')){
    if(mode==='catalog-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    const result=mode==='catalog-invalid'?{collections:{}}:{available:mode!=='catalog-empty',fetched:mode!=='catalog-cache',source:mode==='catalog-cache'?'local_cache':'github_raw',cache_age_seconds:3600,collections:mode==='catalog-empty'?[]:[{id:'ma-fixture',title:'Fixture collection',mod_count:1}]}
    return new Response(JSON.stringify({result:JSON.stringify(result)}))
  }
  if(url.endsWith('/tool/official_share_network_diagnostics')){
    return new Response(JSON.stringify({result:JSON.stringify(mode==='diagnostics-invalid'?{}:{checks:[],cache_available:false})}))
  }
  if(url.endsWith('/tool/share_export')){
    if(mode==='export-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    return new Response(JSON.stringify({result:JSON.stringify(mode==='export-invalid'?{}:{share_json:JSON.stringify({mods:[{name:'fixture'}]})})}))
  }
  if(url.endsWith('/tool/share_import')){
    if(mode==='share-http')return new Response('{}',{status:503})
    if(mode==='share-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    return new Response(JSON.stringify({result:JSON.stringify(mode==='share-invalid'?{}:{items:[{name:'Test mod'}],summary:{total:1}})}))
  }
  if(url.endsWith('/status')){
    window.fixture.statusReads++
    if(window.fixture.statusReads===1){
      if(mode==='load-http')return new Response('{}',{status:503})
      if(mode==='load-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
      if(mode==='load-invalid')return new Response('{}')
    }
    return new Response(JSON.stringify({llm_model:'fixture',llm_endpoint:'https://fixture.invalid/v1',llm_set:mode==='language-keys',api_key_set:mode==='language-keys',tavily_set:mode==='language-keys',language:'en',...(mode.startsWith('background-')?{bg:'old.png'}:{}),...(mode==='background-error'?{bg_error:'BACKGROUND_READ_FAILED'}:{})}))
  }
  if(url.endsWith('/config')){
    if(mode==='config-http')return new Response('{}',{status:503})
    if(mode==='config-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    return new Response(JSON.stringify(mode==='config-invalid'?{}:{ok:true}))
  }
  return new Response('{}')
}
function Fixture(){
  const [language,setLanguage]=useState('en')
  window.fixture.switchLanguage=setLanguage
  return <SettingsPage api="http://fixture.invalid" language={language} onLanguageChange={setLanguage} toast={text=>window.fixture.toasts.push(text)} onStartSharePlan={share=>window.fixture.plans.push(share)} />
}
createRoot(document.getElementById('root')).render(<Fixture/> )
