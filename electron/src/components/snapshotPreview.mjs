import {LocalApiError} from './localApi.mjs'
export function validateSnapshotPreview(data, id){
  const object=v=>v&&typeof v==='object'&&!Array.isArray(v)
  const count=v=>Number.isSafeInteger(v)&&v>=0
  const strings=v=>Array.isArray(v)&&v.every(s=>typeof s==='string')
  const fail=()=>{throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')}
  if(!object(data)||data.snapshot_id!==id||typeof data.confirmation_token!=='string'||!data.confirmation_token.trim()
    ||!strings(data.to_delete)||data.to_delete_count!==data.to_delete.length||!count(data.to_restore_count))fail()
  for(const key of ['baseline','domain_sniffed'])if(data[key]!==undefined&&typeof data[key]!=='boolean')fail()
  if(data.unchanged_count!==undefined&&!count(data.unchanged_count))fail()
  if(data.to_restore!==undefined&&(!strings(data.to_restore)||data.to_restore.length!==data.to_restore_count))fail()
  if(data.missing_in_snapshot!==undefined&&!strings(data.missing_in_snapshot))fail()
  if(data.external_configs!=null&&(!object(data.external_configs)||!count(data.external_configs.action_count)))fail()
  if(data.workshop!=null){
    const w=data.workshop
    if(!object(w)||w.preview_unavailable!==undefined&&typeof w.preview_unavailable!=='boolean')fail()
    if(w.preview_unavailable!==true&&(!strings(w.to_unsubscribe)||!strings(w.to_resubscribe)))fail()
  }
  return data
}
