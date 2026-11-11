import {LocalApiError} from './localApi.mjs'
const object=v=>v&&typeof v==='object'&&!Array.isArray(v)
const count=v=>Number.isSafeInteger(v)&&v>=0
export function validateSnapshotList(rows){
  if(!Array.isArray(rows)||rows.some(row=>!object(row)||typeof row.id!=='string'||!row.id.trim()
    ||typeof row.timestamp!=='number'||!Number.isFinite(row.timestamp)||!Number.isFinite(new Date(row.timestamp*1000).getTime())
    ||!count(row.files_count)||row.trigger_mod_name!==undefined&&typeof row.trigger_mod_name!=='string'
    ||['baseline','valid'].some(k=>row[k]!==undefined&&typeof row[k]!=='boolean')))
    throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  if(new Set(rows.map(row=>row.id)).size!==rows.length)throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  return rows
}
export function validSnapshotStorage(data){
  return !!(object(data)&&count(data.logical_bytes)&&count(data.deduplicated_bytes)
    &&(data.orphan_snapshot_count===undefined||count(data.orphan_snapshot_count))
    &&object(data.snapshots)&&Object.values(data.snapshots).every(row=>object(row)&&count(row.logical_bytes)&&count(row.exclusive_bytes)))
}
