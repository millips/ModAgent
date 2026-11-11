import assert from 'node:assert/strict'
import {readRuntimeStatus, validateRuntimeStatus} from '../src/runtimeStatus.mjs'
const status={llm_model:'fixture',llm_endpoint:'https://fixture.invalid',llm_set:true,api_key_set:false,tavily_set:false}
assert.equal(validateRuntimeStatus(status), status)
for(const invalid of [{},null,{...status,llm_set:'false'},{...status,llm_endpoint:null}]){
  assert.throws(()=>validateRuntimeStatus(invalid),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
}
let calls=[]
assert.equal(await readRuntimeStatus('fixture',{request:async url=>{calls.push(url);return url.endsWith('/health')?{ok:true}:status}}),status)
assert.deepEqual(calls,['fixture/health','fixture/status'])
assert.equal((await readRuntimeStatus('fixture',{request:async url=>url.endsWith('/health')?{ok:true}:{...status,llm_set:false}})).llm_set,false)
await assert.rejects(readRuntimeStatus('fixture',{request:async url=>url.endsWith('/health')?{ok:true}:{}}),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
await assert.rejects(readRuntimeStatus('fixture',{request:async url=>{
  if(url.endsWith('/health'))return {ok:true}
  throw Object.assign(Error('timeout'),{code:'LOCAL_API_TIMEOUT'})
}}),e=>e.code==='LOCAL_API_TIMEOUT')
calls=[]
await assert.rejects(readRuntimeStatus('fixture',{request:async url=>{calls.push(url);return {ok:false}}}),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
assert.deepEqual(calls,['fixture/health'])
const signal=new AbortController().signal
await readRuntimeStatus('fixture',{signal,request:async(url,options)=>{
  assert.equal(options.signal,signal)
  return url.endsWith('/health')?{ok:true}:status
}})
console.log('RUNTIME STATUS PASSED: schema, configured/unconfigured, failed status never becomes setup, health rejection, cancellation propagation')
