import assert from 'node:assert/strict'
import {saveSetupConfiguration,setupFailureMessage} from '../src/setupWorkflow.mjs'
const body={llm_api_key:'fake-test-key',llm_endpoint:'https://example.invalid/v1',llm_model:'fixture',language:'en'}
const calls=[]
await saveSetupConfiguration('http://fixture',body,{store:async()=>({ok:true}),request:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {ok:true}}})
assert.deepEqual(calls,[{url:'http://fixture/config',body:{language:'en'}}])
await assert.rejects(saveSetupConfiguration('fixture',body,{store:async()=>({ok:false,error:'credential_encryption_unavailable'}),request:async()=>{throw Error('must not reach config')}}),e=>e.stage==='credentials'&&setupFailureMessage(e,'en').includes('plaintext'))
await assert.rejects(saveSetupConfiguration('fixture',body,{store:async()=>({ok:true}),request:async()=>({})}),e=>e.credentialsSaved&&setupFailureMessage(e,'zh-CN').includes('密钥已安全保存'))
await assert.rejects(saveSetupConfiguration('fixture',body,{store:()=>new Promise(()=>{}),credentialTimeoutMs:5}),e=>e.restartRequired&&setupFailureMessage(e,'en').includes('may still be writing'))
const fallback=[]
await saveSetupConfiguration('fixture',body,{request:async(_url,opts)=>{fallback.push(JSON.parse(opts.body));return {ok:true}}})
assert.equal(fallback[0].llm_api_key,'fake-test-key')
console.log('SETUP WORKFLOW PASSED: secure route, no redundant reset, no plaintext fallback after secure failure, partial save truthfulness, uncertain IPC timeout, legacy path')
