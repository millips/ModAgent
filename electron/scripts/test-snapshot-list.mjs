import assert from 'node:assert/strict'
import {validateSnapshotList as validate,validSnapshotStorage as storage} from '../src/components/snapshotList.mjs'
const row={id:'s',timestamp:1,files_count:0}
validate([]);validate([row]);validate([{...row,valid:false,baseline:true}])
for(const rows of [null,{},[null],[{...row,id:''}],[row,row],[{...row,timestamp:'1'}],[{...row,timestamp:Infinity}],[{...row,files_count:{}}],[{...row,trigger_mod_name:{}}],[{...row,valid:'false'}]])assert.throws(()=>validate(rows))
const data={logical_bytes:0,deduplicated_bytes:0,snapshots:{s:{logical_bytes:0,exclusive_bytes:0}}}
assert.equal(storage(data),true)
for(const bad of [null,{},[],{...data,logical_bytes:-1},{...data,deduplicated_bytes:'1'},{...data,snapshots:{s:{}}},{...data,orphan_snapshot_count:{}}])assert.equal(storage(bad),false)
console.log('Snapshot list: 10 malformed lists rejected; valid/zero storage accepted; 7 unavailable statistics rejected')
