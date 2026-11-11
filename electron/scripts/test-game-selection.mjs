import assert from 'node:assert/strict'
import {saveGameSelection,importGameSelection,verifyGameSelection} from '../src/gameSelection.mjs'
const game={name:'Fixture',path:'C:\\Fixture',slug:'fixture',game_instance_id:'fixture-id'}
const status={llm_model:'fixture',llm_endpoint:'https://fixture.invalid',llm_set:true,api_key_set:false,tavily_set:false,game_slug:'fixture',game_root:'c:/fixture/',game_instance_id:'fixture-id'}
let writes=[]
assert.equal(await saveGameSelection('fixture',game,{request:async(url,options)=>{
  if(url.endsWith('/config')){writes.push(JSON.parse(options.body));return {ok:true}}
  assert.equal(url,'fixture/status');return status
}}),status)
assert.equal(writes.length,1)
assert.equal(writes[0].game_instance_id,'fixture-id')
for(const invalid of [{}, {ok:false}]) await assert.rejects(saveGameSelection('fixture',game,{request:async()=>invalid}),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
for(const mismatch of [{...status,game_root:'D:/other'},{...status,game_slug:'other'},{...status,game_instance_id:'other'}]){
  await assert.rejects(saveGameSelection('fixture',game,{request:async url=>url.endsWith('/config')?{ok:true}:mismatch}),e=>e.code==='GAME_SELECTION_MISMATCH')
}
await assert.rejects(saveGameSelection('fixture',{name:'invalid'},{request:async()=>{throw Error('must not write')}}),e=>e.code==='GAME_SELECTION_INVALID')
console.log('GAME SELECTION PASSED: confirmed save/readback, malformed ack rejection, path/slug/instance verification, invalid input')
const imported={saved:true,game,mod_scan:{queued:true}}
let imports=[]
assert.equal((await importGameSelection('fixture',{}, {request:async(url,options,limits)=>{
  imports.push(url)
  if(url.endsWith('/games/import')){assert.equal(limits.timeoutMs,120000);return imported}
  return status
}})).result,imported)
assert.deepEqual(imports,['fixture/games/import','fixture/status'])
for(const bad of [{},{saved:true},{saved:true,game:{name:'bad'}}])await assert.rejects(importGameSelection('fixture',{}, {request:async()=>bad}),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
await assert.rejects(importGameSelection('fixture',{}, {request:async url=>url.endsWith('/games/import')?imported:{...status,game_root:'other'}}),e=>e.code==='GAME_SELECTION_MISMATCH')
console.log('GAME IMPORT PASSED: bounded import, readback, no duplicate config save, malformed/mismatched result rejection')
for(const save of [saveGameSelection,importGameSelection]){
  const ack=save===saveGameSelection?{ok:true}:imported
  await assert.rejects(save('fixture',game,{request:async url=>{
    if(!url.endsWith('/status'))return ack
    throw new Error('read unavailable')
  }}),e=>e.confirmedGame?.game_instance_id==='fixture-id')
  await assert.rejects(save('fixture',game,{request:async()=>{throw new Error('write unknown')}}),e=>!e.confirmedGame)
}
let recoveryReads=0
assert.equal(await verifyGameSelection('fixture',game,{request:async(url,options)=>{
  assert.equal(url,'fixture/status');assert.equal(options,undefined);recoveryReads++;return status
}}),status)
assert.equal(recoveryReads,1)
console.log('READ-ONLY RECOVERY PASSED: requires validated write acknowledgement and performs status read only')
