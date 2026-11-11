import assert from 'node:assert/strict'
import {gameImportFeedback} from '../src/components/gameImportFeedback.mjs'
const game={game_instance_id:'fixture'}
const completed={game_instance_id:'fixture',status:'completed',queued:false,detected:3,imported:0}
let cases=0
for(const language of ['zh-CN','en']){
  for(const scan of [undefined,null,[],{}, {...completed,game_instance_id:'other'},
    {...completed,imported:undefined},{...completed,imported:-1},{...completed,imported:4},
    {...completed,detected:'3'},{...completed,missing_roots:[null]},
    {...completed,queued:true},{...completed,error:'PRIVATE_FIXTURE'},
    {...completed,status:'running',queued:'true'},
    {...completed,status:'running',queued:true,error_code:'PRIVATE_FIXTURE'}]){
    const feedback=gameImportFeedback({game,mod_scan:scan},language)
    assert.equal(feedback.kind,'warn');assert.equal(feedback.monitor,false)
    assert.match(feedback.message,/SCAN_STATUS_UNCONFIRMED/)
    assert.doesNotMatch(feedback.message,/PRIVATE_FIXTURE/)
    cases++
  }
  for(const [scan,kind,code,monitor] of [
    [completed,'success',language==='en'?'Scan completed:':'扫描完成：',false],
    [{...completed,missing_roots:['PRIVATE_FIXTURE']},'warn','SCAN_PARTIAL',false],
    [{...completed,status:'failed',error:'PRIVATE_FIXTURE'},'warn','SCAN_FAILED',false],
    [{...completed,status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE'},'warn','SCAN_DIRECTORY_UNREADABLE',false],
    [{game_instance_id:'fixture',status:'running',queued:true},'info',language==='en'?'background':'后台',true]]){
    const feedback=gameImportFeedback({game,mod_scan:scan},language)
    assert.equal(feedback.kind,kind);assert.equal(feedback.monitor,monitor)
    assert.ok(feedback.message.includes(code));assert.doesNotMatch(feedback.message,/PRIVATE_FIXTURE/)
    if(language==='en')assert.doesNotMatch(feedback.message,/[\u4e00-\u9fff]/)
    cases++
  }
}
console.log(`Game import feedback: ${cases} bilingual receipt cases passed`)
