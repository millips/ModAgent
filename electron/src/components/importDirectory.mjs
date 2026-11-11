import {requestLocalJson, LocalApiError} from './localApi.mjs'
const norm = s => String(s).replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase()
export async function saveModDirectory(api,path,scope,{request=requestLocalJson}={}) {
  const result=await request(api+'/mods/import-directory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,expected_game_instance_id:scope})},{timeoutMs:30000})
  if(result?.game_instance_id!==scope || !Array.isArray(result.directories)
    || !result.directories.some(p=>typeof p==='string'&&norm(p)===norm(path)))throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  if(result.status==='running' && result.queued===true)return result
  if(result.status==='completed' && result.queued!==true && !result.error && !result.error_code
    && ['imported','detected'].every(k=>Number.isSafeInteger(result[k])&&result[k]>=0)
    && result.imported<=result.detected
    && (result.missing_roots===undefined||(Array.isArray(result.missing_roots)
      && result.missing_roots.every(path=>typeof path==='string'))))return result
  throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
}
