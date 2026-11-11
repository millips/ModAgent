import assert from 'node:assert/strict'
import {scanInventory} from '../src/components/scanInventory.mjs'

export async function checkScanReceipt(data, ok) {
  const messages=[], events=[]; let refreshes=0
  const result=await scanInventory({api:'receipt-fixture',language:'en',
    fetchImpl:async()=>({ok:true,json:async()=>({result:data})}),
    toast:m=>messages.push(m),emitFeedback:e=>events.push(e),onRefresh:()=>{refreshes++}})
  assert.equal(result.ok,ok,JSON.stringify(data))
  assert.equal(events.includes('scan-complete'),ok)
  assert.equal(refreshes,1)
  if(!ok)assert(messages.some(m=>m.includes('SCAN_UNCONFIRMED')))
}
const base={identified:[{name:'Fixture',file_count:2}],imported:1,identified_total:1,detected:1,truncated:false}
const invalid=[
  {...base,imported:undefined},{...base,imported:'1'},{...base,imported:0.5},
  {...base,imported:Number.MAX_SAFE_INTEGER+1},{...base,imported:2},
  {...base,status:'running'},{...base,status:'future'},
  {...base,identified_total:0},{...base,truncated:'false'},
  {...base,identified_total:2},{...base,truncated:true},
  {...base,detected:-1},{...base,detected:0},{...base,identified:[null]},
  {...base,identified:[{name:{}}]},{...base,identified:[{name:'Fixture',file_count:'2'}]},
  {...base,missing_roots:[{}]},{...base,error_code:'UNKNOWN_FAILURE'},
]
for(const data of invalid)await checkScanReceipt(data,false)
for(const data of [base,{identified:[],imported:0},
  {...base,imported:0},{...base,identified_total:501,detected:501,imported:501,truncated:true},
  {...base,status:'completed'}])await checkScanReceipt(data,true)
console.log(`${invalid.length} malformed scan receipts rejected; 5 valid receipts accepted`)
