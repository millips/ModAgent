import assert from 'node:assert/strict'
import {scanInventory} from '../src/components/scanInventory.mjs'

export async function checkScanReadError(data, language) {
  const messages = [], events = []; let refreshes = 0
  const result = await scanInventory({api:'fixture-read-error', language,
    fetchImpl:async()=>({ok:true,json:async()=>({result:JSON.stringify(data)})}),
    toast:(message)=>messages.push(message), emitFeedback:(event)=>events.push(event),
    onRefresh:()=>{refreshes++}})
  assert.equal(result.ok,false)
  assert.equal(refreshes,1)
  assert(!events.includes('scan-complete'))
  assert(messages.some(message=>message.includes('SCAN_DIRECTORY_UNREADABLE')))
  assert(messages.some(message=>message.includes(language==='en'?'folder permissions':'文件夹权限')))
  assert(!messages.some(message=>message.includes('PRIVATE_FIXTURE')))
  if(language==='en') assert(!messages.some(message=>/[\u4e00-\u9fff]/.test(message)))
}

for(const language of ['zh-CN','en']) {
  await checkScanReadError({status:'failed', error_code:'SCAN_DIRECTORY_UNREADABLE',
    error:'PRIVATE_FIXTURE'},language)
}
console.log('Bilingual scan read-error guidance, no success, refresh and redaction passed')
