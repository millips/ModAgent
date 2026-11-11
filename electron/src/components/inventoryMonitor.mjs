import {requestLocalJson, LocalApiError} from './localApi.mjs'

export async function monitorInventory(api, scope, {signal, isCurrent=()=>true, request=requestLocalJson,
  now=()=>Date.now(), delay=ms=>new Promise(resolve=>setTimeout(resolve,ms)), durationMs=180000} = {}) {
  const deadline=now()+durationMs
  let failures=0, lastState=null
  while(now()<deadline) {
    await delay(Math.min(1000,Math.max(0,deadline-now())))
    if(signal?.aborted || !isCurrent())return {status:'detached'}
    const remaining=deadline-now()
    if(remaining<=0)break
    try {
      const state=await request(`${api}/mods/scan-status?game_instance_id=${encodeURIComponent(scope)}`,{signal},{timeoutMs:Math.min(15000,remaining)})
      if(signal?.aborted || !isCurrent())return {status:'detached'}
      if(state?.game_instance_id!==scope || !['idle','running','completed','failed'].includes(state.status))throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      if(state.status==='completed'){
        if(!['imported','detected'].every(k=>Number.isSafeInteger(state[k])&&state[k]>=0)
          ||state.imported>state.detected||state.error||state.error_code
          ||state.missing_roots!==undefined&&(!Array.isArray(state.missing_roots)
            ||!state.missing_roots.every(path=>typeof path==='string')))throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
        return state
      }
      if(state.status==='failed')return state.error_code==='SCAN_DIRECTORY_UNREADABLE'
        ? {status:'failed',error_code:state.error_code} : {status:'failed'}
      if(state.status==='idle')return {status:'unconfirmed'}
      failures=0
      lastState=state.status
    }catch(error){
      if(signal?.aborted || !isCurrent())return {status:'detached'}
      if(++failures>=3)return {status:'unconfirmed',code:error.code}
    }
  }
  return {status:'unconfirmed',lastState}
}
