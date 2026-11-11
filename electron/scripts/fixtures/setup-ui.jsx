import React from 'react'
import {createRoot} from 'react-dom/client'
import SetupPage from '../../src/components/SetupPage'
window.setupFixture={mode:new URLSearchParams(location.search).get('mode'),toasts:[],done:0,stores:0,requests:[]}
window.modagent={saveSecrets:async()=>{
  window.setupFixture.stores++
  if(window.setupFixture.mode==='credential-error')return {ok:false,error:'credential_encryption_unavailable'}
  if(window.setupFixture.mode==='credential-timeout')return new Promise(()=>{})
  return {ok:true}
}}
window.fetch=async(url,options={})=>{
  window.setupFixture.requests.push({url,body:options.body})
  if(window.setupFixture.mode==='config-http')return new Response('{}',{status:503})
  if(window.setupFixture.mode==='config-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
  return new Response(JSON.stringify(window.setupFixture.mode==='config-invalid'?{}:{ok:true}))
}
createRoot(document.getElementById('root')).render(<SetupPage language={new URLSearchParams(location.search).get('language')||'zh-CN'} api="http://fixture.invalid" toast={text=>window.setupFixture.toasts.push(text)} onDone={()=>window.setupFixture.done++} />)
