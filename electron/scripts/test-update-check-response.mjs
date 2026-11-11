import assert from 'node:assert/strict'
import {validateUpdateCheckResponse} from '../src/components/updateCheckResponse.mjs'
const item={mod_id:'one',name:'Fixture',latest:'2'}
const result={summary:{total:1},updates_available:[item],checked_nexus:1,checked_thunderstore:0,failed_checks:[]}
assert.equal(validateUpdateCheckResponse(result),result)
assert.doesNotThrow(()=>validateUpdateCheckResponse({summary:{total:0},updates_available:[]}))
assert.doesNotThrow(()=>validateUpdateCheckResponse({...result,cancelled:true,updates_available:[]}))
assert.doesNotThrow(()=>validateUpdateCheckResponse({...result,updates_available:[{...item,mod_id:'__proto__',status:'future_status'}]}))
const bad=[null,[],{...result,cancelled:'false'},{...result,checked_nexus:'1'},
  {...result,checked_thunderstore:-1},{...result,summary:[]},{...result,summary:{total:{}}},
  {...result,failed_checks:'failure'},{...result,items:{}},
  ...[{name:{}},{current:[]},{source:{}},{status:{}},{latest:''},{mod_id:''},{mod_id:NaN}].map(patch=>({...result,updates_available:[{...item,...patch}]})),
  {...result,updates_available:[item,item]},
  {...result,updates_available:[{...item,mod_id:1},{...item,mod_id:'1'}]},
]
for(const value of bad)assert.throws(()=>validateUpdateCheckResponse(value),error=>error.code==='LOCAL_API_INVALID_RESPONSE')
console.log(`Update check response: ${bad.length} malformed payloads rejected; empty, cancelled and valid candidates accepted`)
