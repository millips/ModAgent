import assert from 'node:assert/strict'
import {validateSnapshotReceipt as validate} from '../src/components/snapshotReceipt.mjs'
const valid={snapshot_id:'s',complete:true,deleted:0,restored:2,unchanged_verified:1}
assert.equal(validate(valid,'s'),valid)
validate({...valid,complete:false,pending_restore:['a'],external_configs:{complete:false}},'s')
validate({...valid,workshop:{in_sync:false,manual_subscribe:['123']}},'s')
validate({error:'missing'},'s')
validate({...valid,complete:false,audit_log_saved:false,restore_verified:true},'s')
for(const receipt of [{...valid,audit_log_saved:false},{...valid,audit_log_saved:'false'},
  {...valid,restore_verified:'true'}])assert.throws(()=>validate(receipt,'s'))
validate({...valid,complete:false,inventory_cleanup:{complete:false,failed_mod_ids:['fixture']}},'s')
for(const inventory_cleanup of [{complete:false,failed_mod_ids:['fixture']},
  {complete:true,failed_mod_ids:['fixture']},{complete:'false',failed_mod_ids:[]},
  {complete:true,failed_mod_ids:[{}]}])assert.throws(()=>validate({...valid,inventory_cleanup},'s'))
const bad=[null,[],{}, {...valid,snapshot_id:'other'}, {...valid,complete:'true'},
  {...valid,restored:'2'}, {...valid,deleted:-1}, {...valid,unchanged_verified:null},
  {...valid,warning:{}}, {...valid,mods_cleaned:'abc'}, {...valid,pending_delete:['a']},
  {...valid,external_configs:{complete:false}}, {...valid,workshop:{in_sync:'false'}},
  {...valid,workshop:{in_sync:false,manual_subscribe:{}}},
  {...valid,workshop:{in_sync:true,manual_subscribe:['a']}},{error:{}}]
for(const data of bad)assert.throws(()=>validate(data,'s'),/LOCAL_API_INVALID_RESPONSE/)
console.log(`Snapshot receipts: 4 valid / ${bad.length} malformed passed`)
