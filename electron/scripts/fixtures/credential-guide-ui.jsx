import React from 'react'
import {createRoot} from 'react-dom/client'
import CredentialGuide from '../../src/components/CredentialGuide'
const q=new URLSearchParams(location.search),mode=q.get('mode')
window.guideFixture={calls:[],requests:[],toasts:[],opened:[],saved:0}
window.modagent={openExternal:async url=>{window.guideFixture.opened.push(url);return {ok:mode!=='link-error'}},saveSecrets:async body=>{
  window.guideFixture.calls.push(body)
  if(mode==='timeout')return new Promise(()=>{})
  if(mode==='error')return {ok:false,error:'credential_encryption_unavailable'}
  return {ok:true}
}}
if(mode==='unavailable')delete window.modagent.saveSecrets
window.fetch=async(url,options)=>{window.guideFixture.requests.push({url,body:options.body});return new Response(JSON.stringify({ok:true}))}
createRoot(document.getElementById('root')).render(<CredentialGuide provider={q.get('provider')} language={q.get('language')} api="http://fixture.invalid" toast={t=>window.guideFixture.toasts.push(t)} onClose={()=>{}} onSaved={()=>window.guideFixture.saved++}/> )
