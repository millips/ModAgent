import {LocalApiError} from './localApi.mjs'

export function validateScanReceipt(data) {
  const fail=()=>{throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')}
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v)
  const count=v=>Number.isSafeInteger(v)&&v>=0
  if(!object(data)||data.error||data.error_code
    ||data.status!==undefined&&data.status!=='completed'
    ||!Array.isArray(data.identified)||!count(data.imported))fail()
  for(const item of data.identified){
    if(!object(item)||typeof item.name!=='string'||!item.name.trim())fail()
    for(const key of ['mod_id','version','confidence'])
      if(item[key]!==undefined&&typeof item[key]!=='string')fail()
    if(item.file_count!==undefined&&!count(item.file_count))fail()
  }
  for(const key of ['detected','identified_total','unidentified_count','aliases_merged_count'])
    if(data[key]!==undefined&&!count(data[key]))fail()
  if(data.truncated!==undefined&&typeof data.truncated!=='boolean')fail()
  const total=data.identified_total??data.identified.length
  if(data.truncated===true){
    if(data.identified_total===undefined||total<=data.identified.length)fail()
  }else if(total!==data.identified.length)fail()
  if(data.imported>total||data.detected!==undefined&&total>data.detected)fail()
  for(const key of ['scanned_roots','missing_roots'])
    if(data[key]!==undefined&&(!Array.isArray(data[key])||!data[key].every(v=>typeof v==='string')))fail()
  return data
}
