import assert from 'node:assert/strict'
import {saveModDirectory} from '../src/components/importDirectory.mjs'
const good={game_instance_id:'scope',directories:['c:/mods/'],status:'running',queued:true}
assert.equal(await saveModDirectory('fixture','C:\\mods','scope',{request:async(url,options,limits)=>{
  assert.equal(JSON.parse(options.body).expected_game_instance_id,'scope')
  assert.equal(limits.timeoutMs,30000)
  return good
}}),good)
for(const result of [{},{...good,game_instance_id:'other'},{...good,directories:[]},{...good,status:'completed',queued:false},{...good,queued:false}])await assert.rejects(saveModDirectory('fixture','C:/mods','scope',{request:async()=>result}))
const completed={...good,status:'completed',queued:false,imported:0,detected:0}
assert.equal(await saveModDirectory('fixture','C:/mods','scope',{request:async()=>completed}),completed)
for(const result of [{...completed,imported:1},{...completed,detected:Number.MAX_SAFE_INTEGER+1},
  {...completed,missing_roots:[{}]},{...completed,error_code:'UNKNOWN'},
  {...completed,queued:true}])await assert.rejects(saveModDirectory('fixture','C:/mods','scope',{request:async()=>result}))
const partial={...completed,missing_roots:['X:/missing']}
assert.equal(await saveModDirectory('fixture','C:/mods','scope',{request:async()=>partial}),partial)
console.log('IMPORT DIRECTORY PASSED: bound scope, normalized path, queued/completed receipts, malformed rejection')
