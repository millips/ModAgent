import {requestLocalJson, localApiFailure} from './localApi.mjs'
import {validateScanReceipt} from './scanReceipt.mjs'

const activeScans = new Set()
// Scan is metadata import, not an installation. Zero new rows still refreshes UI.
export async function scanInventory({ api, fetchImpl = fetch, toast, emitFeedback, onRefresh,
  language = 'zh-CN', timeoutMs = 120000, refreshTimeoutMs = 15000 }) {
  const en = language === 'en'
  if (activeScans.has(api)) {
    toast(en ? '[SCAN_ALREADY_RUNNING] A scan is already waiting for a result.' : '[SCAN_ALREADY_RUNNING] 已有扫描正在等待结果，请勿重复启动。', 'warn')
    return {ok:false,busy:true}
  }
  activeScans.add(api)
  emitFeedback('scan-start', { source: 'quick-action' })
  try {
    const envelope = await requestLocalJson(api + '/tool/scan_existing_mods', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }, {fetchImpl,timeoutMs})
    const data = typeof envelope.result === 'string' ? JSON.parse(envelope.result) : envelope.result
    if (data?.status === 'failed' && data?.error_code === 'SCAN_DIRECTORY_UNREADABLE') {
      emitFeedback('error', { source: 'scan', code: data.error_code })
      toast('[SCAN_DIRECTORY_UNREADABLE] ' + (en
        ? 'The mod directory could not be read completely. Check folder permissions and drive connectivity, then scan again. No new records from this scan were imported; existing records remain.'
        : '无法完整读取模组目录。请检查文件夹权限和磁盘连接后重新扫描；本次未导入新记录，原有记录保留。'), 'error')
      return {ok:false, code:data.error_code}
    }
    const {imported} = validateScanReceipt(data)
    const missingCount = data.missing_roots?.length || 0
    if (missingCount) {
      toast('[SCAN_PARTIAL] ' + (en
        ? `Scan incomplete: ${missingCount} saved mod directories could not be found. ${imported} new records were imported from available directories. Reconnect the drive or update the saved directories, then scan again. This does not mean those Mods are uninstalled.`
        : `扫描不完整：${missingCount} 个已保存的模组目录未找到。已从可用目录新增导入 ${imported} 条记录。请连接磁盘或更新已保存的目录后重新扫描；不能据此判断其中的 Mod 已卸载。`), 'warn')
      emitFeedback('scan-partial', {count: imported, missingCount})
      return {ok:true, partial:true, imported, missingCount}
    }
    toast(imported > 0 ? (en ? `Scan complete: ${imported} new management records imported.` : `扫描完成：新增导入 ${imported} 条管理记录`)
      : (en ? 'Scan complete: no new management records. Existing Mods may already be recorded.' : '扫描完成：没有新增管理记录；不代表游戏未安装 Mod。'))
    emitFeedback('scan-complete', { count: imported })
    return { ok: true, imported }
  } catch (error) {
    emitFeedback('error', { source: 'scan' })
    toast('[SCAN_UNCONFIRMED] ' + (en ? 'Scan completion was not confirmed. This does not mean no Mods are installed. ' : '扫描完成状态未确认，不能据此判断是否安装了 Mod。')
      + (error?.code ? localApiFailure(error, language) : (en ? 'The scan returned an invalid or failed receipt; check diagnostics.' : '扫描回执异常或报告失败，请检查诊断信息。')), 'error')
    return { ok: false }
  } finally {
    // Prior/background imports can already exist even when this scan adds zero.
    let timer
    try {
      await Promise.race([
        Promise.resolve().then(()=>onRefresh?.()),
        new Promise((_resolve,reject)=>{timer=setTimeout(()=>reject(Error('refresh_timeout')),refreshTimeoutMs)}),
      ])
    } catch (_) {
      toast(en ? '[SCAN_REFRESH_FAILED] The inventory view did not refresh. Reopen the Mod list to check the current records.'
        : '[SCAN_REFRESH_FAILED] 管理清单刷新未完成，请重新打开 Mod 清单核对当前记录。', 'warn')
    } finally { clearTimeout(timer); activeScans.delete(api) }
  }
}
