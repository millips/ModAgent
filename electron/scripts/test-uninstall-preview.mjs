import assert from 'node:assert/strict'
import {validateUninstallPreview} from '../src/components/uninstallPreview.mjs'
const preview={requires_confirmation:true,mod_id:'one',will_unsubscribe:false,will_delete_count:2,blocked_unsafe_count:0,dependents:[]}
assert.equal(validateUninstallPreview(preview,'one'),preview)
assert.doesNotThrow(()=>validateUninstallPreview({...preview,will_unsubscribe:true,will_delete_count:0},'one'))
for(const patch of [{mod_id:'two'},{mod_id:null},{will_unsubscribe:'false'},{will_delete_count:'2'},{will_delete_count:-1},{will_delete_count:1.5},{will_delete_count:null},{blocked_unsafe_count:undefined},{dependents:{}},{dependents:[{}]},{requires_confirmation:'true'},{will_unsubscribe:true}]){
  assert.throws(()=>validateUninstallPreview({...preview,...patch},'one'),error=>error.code==='LOCAL_API_INVALID_RESPONSE')
}
console.log('Uninstall preview: valid local/workshop receipts accepted; 12 malformed impact or identity receipts blocked')
