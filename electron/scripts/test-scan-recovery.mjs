import assert from 'node:assert/strict'
import {scanInventory} from '../src/components/scanInventory.mjs'
const receipts=[]
const base={api:'fixture',toast:(...args)=>receipts.push(args),emitFeedback:()=>{},timeoutMs:10,refreshTimeoutMs:10}
const hung=async(_url,{signal})=>new Response(new ReadableStream({start(c){signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
const first=scanInventory({...base,fetchImpl:hung})
assert.equal((await scanInventory({...base,fetchImpl:hung})).busy,true)
assert.equal((await first).ok,false)
assert(receipts.some(([text])=>text.includes('SCAN_UNCONFIRMED')&&text.includes('可能已送达')))
const success=async()=>new Response(JSON.stringify({result:'{"identified":[],"imported":0}'}))
receipts.length=0
assert.equal((await scanInventory({...base,fetchImpl:success,onRefresh:()=>new Promise(()=>{})})).ok,true)
assert(receipts.some(([text])=>text.includes('SCAN_REFRESH_FAILED')))
assert(!receipts.some(([text])=>text.includes('已刷新')))
assert.equal((await scanInventory({...base,fetchImpl:success,language:'en'})).ok,true)
assert(receipts.some(([text])=>text.includes('Scan complete: no new')))
console.log('SCAN RECOVERY PASSED: duplicate suppression, body timeout, uncertain background state, refresh timeout independent of scan receipt, retry, English')
