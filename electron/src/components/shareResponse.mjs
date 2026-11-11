import { LocalApiError } from './localApi.mjs'

export function readShareResult(envelope) {
  let result
  try { result = JSON.parse(envelope?.result) } catch (_) { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  if (!result || typeof result !== 'object' || Array.isArray(result)) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  if (result.error) throw new LocalApiError('SHARE_VERIFICATION_REJECTED')
  return result
}

export function validateSharePreview(result) {
  const invalid = () => { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  const strings = (obj, keys) => obj && keys.every(k => obj[k] === undefined || typeof obj[k] === 'string')
  if (!Array.isArray(result.items) || !result.summary || !Number.isInteger(result.summary.total)
    || result.summary.total !== result.items.length || !strings(result, ['title','description','warning'])) invalid()
  if (result.items.some(item => !item || typeof item.name !== 'string' || !strings(item,['localized_name','status','version','file_state'])
    || item.installed_match != null && (typeof item.installed_match !== 'object' || Array.isArray(item.installed_match)
      || !strings(item.installed_match,['id','name','version','file_state'])))) invalid()
  for (const key of ['already_installed','needs_verification','needs_source_resolution']) {
    if (result.summary[key] !== undefined && (!Number.isInteger(result.summary[key]) || result.summary[key] < 0)) invalid()
  }
  if (result.game !== undefined && !strings(result.game,['name','slug'])) invalid()
  if (result.official !== undefined && (!strings(result.official,['id','title'])
    || (result.official.warnings !== undefined && (!Array.isArray(result.official.warnings) || result.official.warnings.some(w=>typeof w!=='string'))))) invalid()
  const requirements = result.summary.host_dependency_requirements
  if (requirements !== undefined && (!Array.isArray(requirements) || requirements.some(item =>
    !strings(item,['id','name','status']) || (item.evidence !== undefined && (!Array.isArray(item.evidence) || item.evidence.some(e=>typeof e!=='string')))))) invalid()
  return result
}

export function validateShareExport(result, count) {
  let manifest
  try { manifest = JSON.parse(result.share_json) } catch (_) { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  if (typeof result.share_json !== 'string' || !Array.isArray(manifest?.mods) || (count !== undefined && manifest.mods.length !== count)) {
    throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  }
  return result
}

export function shareRejectionMessage(language) {
  return language === 'en'
    ? 'The share did not pass backend verification. Check the collection code/link, manifest, game and source bindings before retrying. Nothing has been installed.'
    : '分享内容未通过后台核验。请检查合集码或链接、清单、游戏及来源绑定后重试，尚未执行安装。'
}

export function installedShareVersionLabel(item, language) {
  const en = language === 'en'
  const local = item.installed_match?.version?.trim()
  const shared = item.version?.trim()
  if (!local || !shared) return en ? 'Installed; version comparison unavailable' : '已安装；版本尚无法核对'
  if (local !== shared) return en ? `Version differs — local ${local}; shared ${shared}` : `版本不同：本机 ${local}；分享 ${shared}`
  return en ? `Installed; recorded version matches (${local})` : `已安装；记录版本相同（${local}）`
}

export function shareFileStateLabel(item, language) {
  const en=language==='en'
  const names=en?{enabled_files:'active files',disabled_files:'disabled files'}:{enabled_files:'启用文件',disabled_files:'停用文件'}
  const local=item.installed_match?.file_state, shared=item.file_state
  if(!Object.hasOwn(names,local)||!Object.hasOwn(names,shared))return en?'File state comparison unavailable':'文件启停状态尚无法核对'
  return en?`File state ${local===shared?'matches':'differs'} — local ${names[local]}; shared ${names[shared]}`:`文件启停状态${local===shared?'相同':'不同'}：本机${names[local]}；分享${names[shared]}`
}
