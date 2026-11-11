import assert from 'node:assert/strict'
import {scanInventory} from '../src/components/scanInventory.mjs'

export async function checkPartialScan(data,language) {
  const messages=[],events=[]; let refreshes=0
  const result=await scanInventory({api:'partial-fixture',language,
    fetchImpl:async()=>({ok:true,json:async()=>({result:data})}),
    toast:(message,kind)=>messages.push({message,kind}),
    emitFeedback:event=>events.push(event),onRefresh:()=>{refreshes++}})
  assert.equal(result.ok,true)
  assert.equal(result.partial,true)
  assert.equal(result.imported,data.imported)
  assert.equal(refreshes,1)
  assert(!events.includes('scan-complete'))
  assert(events.includes('scan-partial'))
  assert(messages.some(m=>m.kind==='warn'&&m.message.includes('SCAN_PARTIAL')))
  assert(messages.some(m=>m.message.includes(language==='en'?'saved mod directories':'已保存的模组目录')))
  assert(!messages.some(m=>m.message.includes('PRIVATE_FIXTURE')))
  if(language==='en')assert(!messages.some(m=>/[\u4e00-\u9fff]/.test(m.message)))
}
for(const language of ['en','zh-CN'])for(const imported of [0,1]) {
  await checkPartialScan({identified:[{name:'Fixture'}],imported,
    missing_roots:['PRIVATE_FIXTURE']},language)
}
console.log('4 bilingual partial scan scenarios passed')
