import assert from 'node:assert/strict'
import {requestLocalJson, localApiFailure} from '../src/components/localApi.mjs'

const options = fetchImpl => ({fetchImpl, timeoutMs:20})
assert.deepEqual(await requestLocalJson('https://fixture.invalid', {}, options(async()=>new Response('{"ok":true}'))), {ok:true})
await assert.rejects(requestLocalJson('fixture', {}, options(async()=>new Response('{}',{status:503}))), e=>e.code==='LOCAL_API_HTTP' && e.status===503)
await assert.rejects(requestLocalJson('fixture', {}, options(async()=>new Response('broken'))), e=>e.code==='LOCAL_API_INVALID_RESPONSE')
await assert.rejects(requestLocalJson('fixture', {}, options(async()=>{throw new Error('secret-key')})), e=>e.code==='LOCAL_API_UNAVAILABLE' && !e.message.includes('secret'))
await assert.rejects(requestLocalJson('fixture', {}, options((_url,{signal})=>new Promise((_resolve,reject)=>{
  signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
}))), e=>e.code==='LOCAL_API_TIMEOUT')
await assert.rejects(requestLocalJson('fixture', {}, options(async(_url,{signal})=>new Response(new ReadableStream({start(c){
  signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))
}})))), e=>e.code==='LOCAL_API_TIMEOUT')
const parent=new AbortController()
const pending=requestLocalJson('fixture', {signal:parent.signal}, options((_url,{signal})=>new Promise((_resolve,reject)=>{
  signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
})))
parent.abort()
await assert.rejects(pending, e=>e.name==='AbortError')
assert.match(localApiFailure({code:'LOCAL_API_TIMEOUT'},'en'), /may still/)
assert.match(localApiFailure({code:'LOCAL_API_TIMEOUT'},'zh-CN'), /可能已送达/)
assert.match(localApiFailure({code:'GAME_SELECTION_MISMATCH'},'en'), /service replied.*does not match/)
assert.match(localApiFailure({code:'GAME_SELECTION_MISMATCH'},'zh-CN'), /后台已回复.*不一致/)
assert.match(localApiFailure({code:'GAME_SELECTION_INVALID'},'en'), /incomplete/)
assert.match(localApiFailure({code:'GAME_SELECTION_INVALID'},'zh-CN'), /不完整/)
for(const code of ['LOCAL_API_HTTP','LOCAL_API_UNAVAILABLE','LOCAL_API_TIMEOUT','LOCAL_API_INVALID_RESPONSE','UNKNOWN']){
  for(const language of ['en','zh-CN']){
    const message=localApiFailure({code,status:503,message:'secret-key'},language,{mutation:true})
    assert.match(message,language==='en'?/may already have changed/:/可能已经修改/)
    assert.match(message,language==='en'?/before retrying/:/再决定是否重试/)
    assert.doesNotMatch(message,/secret-key|Check the service and retry|Check the app connection and retry/)
  }
}
assert.match(localApiFailure({code:'LOCAL_API_HTTP',status:503},'en'),/Check the service and retry/)
console.log('LOCAL API PASSED: transport, redaction, deadlines, cancellation, bilingual read/write failure guidance')
