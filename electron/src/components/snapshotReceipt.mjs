import {LocalApiError} from './localApi.mjs'

export function validateSnapshotReceipt(data, snapshotId) {
  const fail=()=>{throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')}
  const object=v=>v&&typeof v==='object'&&!Array.isArray(v)
  const count=v=>Number.isSafeInteger(v)&&v>=0
  if(!object(data))fail()
  if(data.error){if(typeof data.error!=='string')fail();return data}
  if(data.snapshot_id!==snapshotId||typeof data.complete!=='boolean')fail()
  for(const key of ['audit_log_saved','restore_verified'])
    if(data[key]!==undefined&&typeof data[key]!=='boolean')fail()
  if(data.audit_log_saved===false&&data.complete)fail()
  for(const key of ['deleted','restored','unchanged_verified'])if(!count(data[key]))fail()
  for(const key of ['warning','safety_note'])if(data[key]!==undefined&&typeof data[key]!=='string')fail()
  for(const key of ['pending_delete','pending_restore','missing_in_snapshot','mods_cleaned']){
    if(data[key]!==undefined&&!Array.isArray(data[key]))fail()
  }
  if(data.complete&&['pending_delete','pending_restore','missing_in_snapshot'].some(k=>data[k]?.length))fail()
  if(data.inventory_cleanup!==undefined){
    const c=data.inventory_cleanup
    if(!object(c)||typeof c.complete!=='boolean'||!Array.isArray(c.failed_mod_ids)
      ||!c.failed_mod_ids.every(id=>typeof id==='string')
      ||c.complete&&c.failed_mod_ids.length||data.complete&&!c.complete)fail()
  }
  if(data.external_configs!=null&&(!object(data.external_configs)
    ||typeof data.external_configs.complete!=='boolean'||data.complete&&!data.external_configs.complete))fail()
  if(data.workshop!=null){
    const w=data.workshop
    if(!object(w)||typeof w.in_sync!=='boolean')fail()
    for(const key of ['unsubscribed','resubscribed','manual_unsubscribe','manual_subscribe']){
      if(w[key]!==undefined&&(!Array.isArray(w[key])||!w[key].every(id=>typeof id==='string'||count(id))))fail()
    }
    if(w.in_sync&&(w.manual_unsubscribe?.length||w.manual_subscribe?.length))fail()
  }
  return data
}
