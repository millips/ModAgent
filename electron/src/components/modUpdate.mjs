import {requestLocalJson, localApiFailure, LocalApiError} from './localApi.mjs'

export async function updateMod(api, modId, language, requestOptions = {}) {
  const en = language === 'en'
  const envelope = await requestLocalJson(api + '/tool/mod_update', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mod_id:String(modId)}),
  }, {timeoutMs:120000, ...requestOptions})
  let data
  try { data=JSON.parse(envelope.result) } catch (_) { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
  if (data?.error) {
    const advice = {
      tls_error: en ? 'Certificate verification failed. Check system time and proxy trust; do not disable verification.' : '证书验证失败。请检查系统时间及代理证书信任，不要关闭证书校验。',
      timeout: en ? 'The request timed out. Check connectivity or proxy settings before retrying.' : '请求超时。请检查网络或代理设置后再试。',
      access_denied: en ? 'The source denied access. Check authorization and site restrictions.' : '来源站拒绝访问。请检查授权及站点访问限制。',
      rate_limited: en ? 'The source rate-limited this request. Try again later.' : '来源站限流，请稍后再试。',
      redirect_blocked: en ? 'The source redirect was blocked. Review the Mod page or try later; do not forward keys.' : '来源跳转已阻止。请核对维护页或稍后再试，不要转发密钥。',
    }
    if (['UPDATE_SOURCE_FAILED','UPDATE_DOWNLOAD_FAILED'].includes(data.error_code)
        && Object.hasOwn(advice, data.failure_kind)) {
      return {ok:false, message:`[${data.error_code}] ${advice[data.failure_kind]} `
        + (en ? 'The old version is unchanged.' : '旧版本未改动。')}
    }
    const message = data.error_code === 'UPDATE_SNAPSHOT_FAILED'
      ? (en ? '[UPDATE_SNAPSHOT_FAILED] The pre-update snapshot was not confirmed. The old version was not removed. Check disk space, folder permissions and the snapshot list; keep existing backups and the archive.' : '[UPDATE_SNAPSHOT_FAILED] 更新前快照未确认完成，旧版本未移除。请检查磁盘空间、目录权限和快照列表，保留现有备份及安装包。')
      : data.error_code === 'UPDATE_OLD_FILES_UNCONFIRMED'
      ? (en ? '[UPDATE_OLD_FILES_UNCONFIRMED] Old files changed or could not be verified. Update stopped without removing them. Preserve external changes and review before updating again.' : '[UPDATE_OLD_FILES_UNCONFIRMED] 旧文件已变化或无法核验。更新已停止，未移除旧文件。请保留外部改动，重新检查后再更新。')
      : data.error_code === 'UPDATE_SOURCE_FAILED'
      ? (en ? '[UPDATE_SOURCE_FAILED] Latest version information could not be read. Check source connectivity, authorization and the Mod page. The old version is unchanged.' : '[UPDATE_SOURCE_FAILED] 无法读取最新版本信息。请检查来源站连接、授权和维护页；旧版本未改动。')
      : data.error_code === 'UPDATE_DOWNLOAD_FAILED'
      ? (en ? '[UPDATE_DOWNLOAD_FAILED] The update download did not produce a valid archive. Check source connectivity, authorization and download diagnostics. The old version is unchanged.' : '[UPDATE_DOWNLOAD_FAILED] 新版下载未产生有效安装包。请检查来源站连接、授权和下载记录；旧版本未改动。')
      : data.error_code === 'UPDATE_OWNERSHIP_UNCONFIRMED'
      ? (en ? '[UPDATE_OWNERSHIP_UNCONFIRMED] File ownership could not be verified. The old version was not removed; rescan and review inventory records before updating.' : '[UPDATE_OWNERSHIP_UNCONFIRMED] 无法核验文件归属。旧版本未移除，请重新扫描并核对管理记录后再更新。')
      : data.error_code === 'UPDATE_TARGET_OWNED'
      ? (en ? '[UPDATE_TARGET_OWNED] New files conflict with another Mod. The old version was not removed; review conflicts and compatible versions.' : '[UPDATE_TARGET_OWNED] 新版文件与其他 Mod 冲突。旧版本未移除，请先核对冲突和兼容版本。')
      : data.error_code === 'UPDATE_PREVIEW_FAILED'
      ? (en ? '[UPDATE_PREVIEW_FAILED] Install destinations could not be verified. The old version was not removed; check the archive and game support.' : '[UPDATE_PREVIEW_FAILED] 无法核验新版安装路径。旧版本未移除，请检查安装包和游戏适配。')
      : data.error_code === 'UPDATE_SHARED_FILES'
      ? (en ? '[UPDATE_SHARED_FILES] Update was not started: other Mods still use shared files. Review shared dependencies and compatible versions; do not delete these files.' : '[UPDATE_SHARED_FILES] 更新未开始：其他 Mod 仍在使用共享文件。请核对共享依赖和兼容版本，不要直接删除这些文件。')
      : data.recovery_required === true
      ? (en ? '[MOD_UPDATE_RECOVERY_REQUIRED] Update is not confirmed and some files may have changed. Keep the files and pre-update snapshot, close the game and review task diagnostics before retrying.' : '[MOD_UPDATE_RECOVERY_REQUIRED] 更新未确认，部分文件可能已改变。请保留文件与更新前快照，关闭游戏并核对任务诊断，不要重复更新。')
      : data.restored_previous === true
      ? (en ? '[MOD_UPDATE_RESTORED] Update failed; the backend verified restoration of the previous version.' : '[MOD_UPDATE_RESTORED] 更新失败；后台已核验恢复到更新前版本。')
      : data.restored_previous === false
        ? (en ? '[MOD_UPDATE_RECOVERY_REQUIRED] Update failed and automatic restoration was incomplete. Close the game and review the pre-update snapshot before retrying.' : '[MOD_UPDATE_RECOVERY_REQUIRED] 更新失败且自动恢复未完整成功。请关闭游戏，先检查更新前快照，不要重复更新。')
        : (en ? '[MOD_UPDATE_REJECTED] The backend rejected or failed the update. Check source alignment, connectivity and task diagnostics.' : '[MOD_UPDATE_REJECTED] 后台拒绝更新或报告失败，请检查来源对齐、网络及任务诊断。')
    return {ok:false,message}
  }
  if (!data || data.requires_confirmation || data.cancelled
    || (data.status && !['completed','success','updated'].includes(data.status))
    || typeof data.updated !== 'string' || !data.updated.trim()
    || typeof data.version !== 'string' || !data.version.trim()
    || typeof data.snapshot_id !== 'string' || !data.snapshot_id.trim()) {
    throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
  }
  const warning = data.warning_code === 'UPDATE_CACHE_CLEANUP_UNCONFIRMED'
    ? (en ? '[UPDATE_CACHE_CLEANUP_UNCONFIRMED] Update completed, but cache cleanup is unconfirmed. Check the download cache later; do not repeat the update.' : '[UPDATE_CACHE_CLEANUP_UNCONFIRMED] 更新已完成，但缓存清理未确认。可稍后检查下载缓存，不要因此重复更新。')
    : ''
  return {ok:true, data, warning}
}

export const updateFailure = (error, language) => '[MOD_UPDATE_UNCONFIRMED] ' + localApiFailure(error, language, {mutation:true})
