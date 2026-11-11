import assert from 'node:assert/strict'
import {updateMod} from '../src/components/modUpdate.mjs'
const call=data=>updateMod('fixture','id','en',{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify(data)}))})
assert.equal((await call({updated:'Fixture',version:'2',snapshot_id:'snap'})).ok,true)
for(const data of [{},{updated:'Fixture'},{requires_confirmation:true},{status:'partial'},{updated:'Fixture',version:'2',snapshot_id:'snap',status:'manual_action_required'}]) {
  await assert.rejects(call(data),error=>error.code==='LOCAL_API_INVALID_RESPONSE')
}
assert((await call({error:'private backend detail',restored_previous:true})).message.includes('MOD_UPDATE_RESTORED'))
assert((await call({error:'private backend detail',restored_previous:false})).message.includes('MOD_UPDATE_RECOVERY_REQUIRED'))
assert(!(await call({error:'private backend detail'})).message.includes('private backend detail'))
for (const language of ['zh','en']) {
  const completed = await updateMod('fixture','id',language,{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify({
    updated:'Fixture',version:'2',snapshot_id:'snap',warning_code:'UPDATE_CACHE_CLEANUP_UNCONFIRMED',warning:'PRIVATE',
  })}))})
  assert.equal(completed.ok,true)
  assert(completed.warning.includes('UPDATE_CACHE_CLEANUP_UNCONFIRMED'))
  assert(!completed.warning.includes('PRIVATE'))
  for (const kind of ['tls_error','timeout','access_denied','rate_limited','redirect_blocked']) {
    const failed = await updateMod('fixture','id',language,{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify({
      error:'PRIVATE', error_code:'UPDATE_SOURCE_FAILED', failure_kind:kind,
    })}))})
    assert.equal(failed.ok,false)
    assert(failed.message.includes(language === 'en' ? 'old version is unchanged' : '旧版本未改动'))
    assert(!failed.message.includes('PRIVATE'))
    if (kind === 'tls_error') assert(failed.message.includes(language === 'en' ? 'do not disable verification' : '不要关闭证书校验'))
  }
  for (const code of ['UPDATE_TARGET_OWNED','UPDATE_PREVIEW_FAILED','UPDATE_OWNERSHIP_UNCONFIRMED','UPDATE_SOURCE_FAILED','UPDATE_DOWNLOAD_FAILED','UPDATE_OLD_FILES_UNCONFIRMED','UPDATE_SNAPSHOT_FAILED']) {
    const blocked = await updateMod('fixture','id',language,{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify({
      error:'PRIVATE', error_code:code, write_performed:false, retryable:false,
    })}))})
    assert.equal(blocked.ok,false)
    assert(blocked.message.includes(code))
    assert(!blocked.message.includes('PRIVATE'))
  }
  const shared = await updateMod('fixture','id',language,{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify({
    error:'PRIVATE', error_code:'UPDATE_SHARED_FILES', write_performed:false, retryable:false,
  })}))})
  assert.equal(shared.ok,false)
  assert(shared.message.includes('UPDATE_SHARED_FILES'))
  assert(!shared.message.includes('PRIVATE'))
  const result = await updateMod('fixture','id',language,{fetchImpl:async()=>new Response(JSON.stringify({result:JSON.stringify({
    error:'PRIVATE', error_code:'UPDATE_REMOVAL_INCOMPLETE', recovery_required:true,
    snapshot_restore_skipped:true, retryable:false,
  })}))})
  assert.equal(result.ok,false)
  assert(result.message.includes('MOD_UPDATE_RECOVERY_REQUIRED'))
  assert(!result.message.includes('PRIVATE'))
  assert(!result.message.includes('MOD_UPDATE_REJECTED'))
}
await assert.rejects(updateMod('fixture','id','en',{timeoutMs:10,fetchImpl:async(_url,{signal})=>new Response(new ReadableStream({start(c){signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))}),error=>error.code==='LOCAL_API_TIMEOUT')
console.log('MOD UPDATE PASSED: strict success receipt, partial/waiting/malformed rejection, rollback distinction, safe errors and hanging body timeout')
