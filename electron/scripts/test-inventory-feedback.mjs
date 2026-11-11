import assert from 'node:assert/strict'
import {monitorInventory} from '../src/components/inventoryMonitor.mjs'
import {inventoryFeedback} from '../src/components/inventoryFeedback.mjs'

export async function checkBackgroundReceipt(data,language){
  let time=0
  const state=await monitorInventory('fixture',data.game_instance_id,{now:()=>time,
    delay:async ms=>{time+=ms},request:async()=>data})
  assert.equal(state.status,data.status)
  const result=inventoryFeedback(state,language)
  assert(!result.message.includes('PRIVATE_FIXTURE'))
  if(language==='en')assert(!/[\u4e00-\u9fff]/.test(result.message))
  if(data.status==='failed'&&data.error_code==='SCAN_DIRECTORY_UNREADABLE'){
    assert(result.message.includes('SCAN_DIRECTORY_UNREADABLE'))
    assert(result.message.includes(language==='en'?'permissions':'权限'))
  }else if(data.missing_roots?.length){
    assert(result.message.includes('SCAN_PARTIAL'))
    assert.equal(result.kind,'warn')
    assert(!result.message.includes('Scan completed:'))
  }else if(data.status==='completed')assert(result.message.includes(language==='en'?'Scan completed:':'扫描完成'))
}
const complete={game_instance_id:'fixture',status:'completed',imported:1,detected:1}
for(const language of ['en','zh-CN'])for(const data of [complete,
  {...complete,missing_roots:['PRIVATE_FIXTURE']},
  {game_instance_id:'fixture',status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE',error:'PRIVATE_FIXTURE'},
  {game_instance_id:'fixture',status:'failed',error:'PRIVATE_FIXTURE'}])await checkBackgroundReceipt(data,language)
console.log('8 bilingual background feedback scenarios passed')
