import React from 'react'
import {createRoot} from 'react-dom/client'
import CommunityImportDialog from '../../src/components/CommunityImportDialog'
import ShareExportDialog from '../../src/components/ShareExportDialog'
const mode=new URLSearchParams(location.search).get('mode')||'valid'
const exported=mode.startsWith('export-')
window.shareFixture={requests:0,toasts:[],plans:[],downloads:0}
if(mode.startsWith('export-copy-'))Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{
  window.shareFixture.copies=(window.shareFixture.copies||0)+1
  window.shareFixture.copiedText=text
  if(mode==='export-copy-timeout')return new Promise(resolve=>{window.shareFixture.finishCopy=resolve})
  await new Promise(resolve=>setTimeout(resolve,40))
  if(mode==='export-copy-error')throw Error('private clipboard exception')
}}})
if(mode==='export-saveerror')Storage.prototype.setItem=function(){throw new DOMException('Storage full','QuotaExceededError')}
HTMLAnchorElement.prototype.click=function(){window.shareFixture.downloads++}
window.modagent={openExternal:async()=>{
  window.shareFixture.opens=(window.shareFixture.opens||0)+1
  if(mode==='export-page-timeout')return new Promise(()=>{})
  await new Promise(resolve=>setTimeout(resolve,40))
  if(mode==='export-page-error')throw Error('private native exception')
  return {ok:true}
},saveShareFile:async ({filename})=>{
  await new Promise(resolve=>setTimeout(resolve,40))
  if(mode==='export-cancel')return {ok:false,cancelled:true}
  if(mode==='export-diskerror')return {ok:false,error:'SHARE_SAVE_FAILED'}
  window.shareFixture.downloads++
  return {ok:true,filename}
}}
window.fetch=async (_url,options)=>{
  window.shareFixture.requests++
  window.shareFixture.lastRequest={url:_url,body:JSON.parse(options.body)}
  if(mode.endsWith('http'))return new Response('{}',{status:503})
  if(mode.endsWith('body'))return new Response(new ReadableStream({start(c){options.signal?.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
  const result=mode.endsWith('invalid')?{}:exported?{share_json:'{"mods":[{"name":"Fixture"}]}',manifest:{submission:{id:'test-submission'}}}:{items:[{name:'Fixture',status:'ready_for_source_verification'}],summary:{total:1},title:'Verified fixture',game:{slug:'fixture'}}
  if(mode==='en-prerequisite')result.summary.host_dependency_requirements=[{id:'loader',name:'Fixture loader',status:'base_environment_not_found'}]
  if(mode==='en-included')result.summary.host_dependency_requirements=[{id:'loader',name:'Fixture loader',status:'included_collection'}]
  if(mode==='en-empty'){result.items=[];result.summary.total=0}
  if(mode.startsWith('en-version-'))result.items=[{name:'Fixture',status:'already_installed',version:'1',installed_match:{id:'local',version:mode==='en-version-different'?'2':mode==='en-version-matching'?'1':''}}]
  if(mode==='en-version-different'){result.items[0].file_state='enabled_files';result.items[0].installed_match.file_state='disabled_files'}
  if(mode.startsWith('official-')){
    result.source_kind=mode==='official-wrong-kind'?'private':'official_collection'
    result.official={id:mode==='official-mismatch'?'ma-other-000003':'ma-repo-000002',title:'Fixture official collection'}
  }
  if(mode==='en-unknown'){
    result.items[0].status='future_backend_status'
    result.summary.host_dependency_requirements=[{id:'loader',name:'Fixture loader',status:'future_dependency_status'}]
  }
  return new Response(JSON.stringify({result:JSON.stringify(result)}))
}
const props={api:'http://fixture.invalid',language:mode.startsWith('en-')||mode.startsWith('official-')?'en':'zh-CN',toast:text=>window.shareFixture.toasts.push(text),onClose:()=>{}}
createRoot(document.getElementById('root')).render(exported
  ? <ShareExportDialog {...props} mods={[{id:'1',name:'Fixture',sourceKey:'github',sourceUrl:'https://example.com/fixture'}]} />
  : <CommunityImportDialog {...props} onPlan={plan=>window.shareFixture.plans.push(plan)} />)
