import assert from 'node:assert/strict'
import {validateSnapshotPreview as validate} from '../src/components/snapshotPreview.mjs'
const good={snapshot_id:'s',confirmation_token:'token',to_delete:[],to_delete_count:0,to_restore_count:1}
validate(good,'s')
validate({...good,baseline:false,domain_sniffed:true,unchanged_count:0,to_restore:['file'],missing_in_snapshot:['missing'],external_configs:{action_count:0},workshop:{to_unsubscribe:['123'],to_resubscribe:[]}},'s')
const bad=[null,[],{}, {...good,snapshot_id:'other'},{...good,confirmation_token:' '},
  {...good,to_delete:[{}]}, {...good,to_delete_count:1},{...good,to_restore_count:'1'},
  {...good,baseline:'false'},{...good,domain_sniffed:'false'}, {...good,unchanged_count:{}},
  {...good,to_restore:[]},{...good,missing_in_snapshot:'missing'},
  {...good,external_configs:{action_count:'2'}},{...good,external_configs:[]},
  {...good,workshop:{to_unsubscribe:'123',to_resubscribe:[]}},
  {...good,workshop:{to_unsubscribe:[],to_resubscribe:[{}]}}]
for(const data of bad)assert.throws(()=>validate(data,'s'),/LOCAL_API_INVALID_RESPONSE/)
console.log(`Snapshot preview: 2 valid / ${bad.length} malformed passed`)
