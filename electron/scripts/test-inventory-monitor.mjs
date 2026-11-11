import assert from 'node:assert/strict'
import {monitorInventory} from '../src/components/inventoryMonitor.mjs'
import {requestLocalJson} from '../src/components/localApi.mjs'
const scope='fixture-instance'
const complete={game_instance_id:scope,status:'completed',imported:0,detected:3}
const run=async states=>{
  let time=0,calls=0
  const result=await monitorInventory('fixture',scope,{now:()=>time,delay:async ms=>{time+=ms},durationMs:6000,request:async()=>{
    const item=states[Math.min(calls++,states.length-1)]
    if(item instanceof Error)throw item
    return item
  }})
  return {result,calls}
}
assert.deepEqual((await run([complete])).result,complete)
assert.equal((await run([{game_instance_id:scope,status:'failed',error:'secret'}])).result.status,'failed')
assert.equal((await run([{game_instance_id:scope,status:'idle'}])).result.status,'unconfirmed')
assert.equal((await run([{...complete,game_instance_id:'other'}])).calls,3)
assert.equal((await run([{...complete,detected:'3'}])).result.status,'unconfirmed')
for(const data of [{...complete,missing_roots:[{}]},
  {...complete,imported:4},{...complete,detected:Number.MAX_SAFE_INTEGER+1},
  {...complete,error_code:'UNKNOWN'}])assert.equal((await run([data])).result.status,'unconfirmed')
assert.deepEqual((await run([{game_instance_id:scope,status:'failed',
  error_code:'SCAN_DIRECTORY_UNREADABLE',error:'secret'}])).result,
  {status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE'})
assert.deepEqual((await run([Error('offline'),complete])).result,complete)
const failed=await run([Error('offline')]);assert.equal(failed.calls,3);assert.equal(failed.result.status,'unconfirmed')
assert.equal((await run([{game_instance_id:scope,status:'running'}])).result.lastState,'running')
const detached=await monitorInventory('fixture',scope,{delay:async()=>{},isCurrent:()=>false,request:async()=>{throw Error('must not query old scope')}})
assert.equal(detached.status,'detached')
let calls=0
const hung=await monitorInventory('fixture',scope,{delay:async()=>{},request:(url,options)=>{
  calls++
  return requestLocalJson(url,options,{timeoutMs:5,fetchImpl:async(_url,{signal})=>new Response(new ReadableStream({start(c){signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))})
}})
assert.equal(calls,3);assert.equal(hung.status,'unconfirmed');assert.equal(hung.code,'LOCAL_API_TIMEOUT')
console.log('INVENTORY MONITOR PASSED: completed/failed/idle, malformed and wrong scope, transient recovery, repeated errors, deadline, detachment, real body timeout')
