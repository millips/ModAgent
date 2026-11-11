import assert from 'node:assert/strict'
import {validateTogglePreview as validate} from '../src/components/togglePreview.mjs'
const preview={requires_confirmation:true,action:'disable',target:{id:'a'},confirmation_token:'token',dependents:[{id:'b',name:'Dependent'}],decision_support:{summary:'Impact',player_impact:[{name:'A',role_label:'Target',functionality_lost:'Feature'}]}}
assert.equal(validate(preview,'a',false),preview)
validate({requires_confirmation:true,action:'enable',target:{id:'a'},dependencies:[{id:'b'}]},'a',true)
validate({blocked:true,requires_external_manager:true,target:{id:'a'},note:'Steam'},'a',false)
validate({blocked:true,action:'enable',target:{id:'a'},missing_dependencies:['b']},'a',true)
const bad=[null,[],{}, {...preview,target:{id:'b'}},{...preview,confirmation_token:''},
  {...preview,requires_confirmation:'true'},{...preview,blocked:'false'},{...preview,note:{}},
  {...preview,dependents:{}},{...preview,dependents:[null]},{...preview,dependents:[{id:'b',name:{}}]},
  {...preview,missing_dependencies:[{}]},{...preview,decision_support:{summary:{}}},
  {...preview,decision_support:{player_impact:'text'}},{...preview,decision_support:{retained:[null]}},
  {...preview,requires_external_manager:true},{...preview,action:'enable'}]
for(const v of bad)assert.throws(()=>validate(v,'a',false),/LOCAL_API_INVALID_RESPONSE/)
console.log(`Toggle preview: 4 valid and ${bad.length} malformed cases passed`)
