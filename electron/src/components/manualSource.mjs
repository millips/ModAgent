import {LocalApiError} from './localApi.mjs'

export function validateSourceReceipt(envelope, localId, candidate, confirmed=false) {
  const fail=()=>{throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')}
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v)
  let result
  try { result=JSON.parse(envelope?.result) } catch { fail() }
  if(!object(result)||result.error)fail()
  if(confirmed){
    if(result.bound!==true||result.requires_confirmation||result.source!==candidate.source
      ||result.source_key!==String(candidate.source_key))fail()
  }else if(result.requires_confirmation!==true||result.bound)fail()
  const preview=result.preview
  if(!object(preview)||!object(preview.local)||String(preview.local.mod_id)!==String(localId))fail()
  const detail=candidate.source==='nexus'?preview.nexus:preview.source
  if(!object(detail))fail()
  if(candidate.source==='nexus'){
    if(!Number.isSafeInteger(detail.mod_id)||detail.mod_id<=0||String(detail.mod_id)!==String(candidate.source_key))fail()
  }else if(candidate.source==='thunderstore'){
    if(detail.kind!=='thunderstore'||detail.source_key!==candidate.source_key)fail()
    const parsed=parseManualSourceUrl(detail.url)
    if(!parsed||parsed.source!==candidate.source||parsed.source_key!==candidate.source_key)fail()
  }else fail()
  for(const key of ['name','version'])if(typeof detail[key]!=='string')fail()
  return result
}

export function parseManualSourceUrl(rawUrl) {
  try {
    const url = new URL(String(rawUrl || '').trim())
    if (url.protocol !== 'https:' || url.username || url.password) return null
    const host = url.hostname.toLowerCase()
    const nexus = url.pathname.match(/\/mods\/(\d+)/i)
    if ((host === 'nexusmods.com' || host.endsWith('.nexusmods.com')) && nexus) {
      return {source:'nexus',source_key:nexus[1],source_url:url.href}
    }
    const thunder = url.pathname.match(/\/c\/[^/]+\/p\/([^/]+)\/([^/?#]+)/i)
    if ((host === 'thunderstore.io' || host.endsWith('.thunderstore.io')) && thunder) {
      return {source:'thunderstore',source_key:`${decodeURIComponent(thunder[1])}-${decodeURIComponent(thunder[2])}`,source_url:url.href}
    }
    return null
  } catch (_) { return null }
}
