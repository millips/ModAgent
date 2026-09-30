// Scan is metadata import, not an installation. Zero new rows still refreshes UI.
export async function scanInventory({ api, fetchImpl = fetch, toast, emitFeedback, onRefresh }) {
  emitFeedback('scan-start', { source: 'quick-action' })
  try {
    const response = await fetchImpl(api + '/tool/scan_existing_mods', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    })
    const envelope = await response.json()
    const data = typeof envelope.result === 'string' ? JSON.parse(envelope.result) : envelope.result
    if (!response.ok || !data || data.error || !Array.isArray(data.identified)
      || ['failed', 'blocked', 'cancelled'].includes(data.status)) throw Error('invalid_scan_receipt')
    const imported = Number.isInteger(data.imported) ? data.imported : data.identified.length
    if (imported < 0) throw Error('invalid_scan_count')
    toast(imported > 0 ? `扫描完成：新增导入 ${imported} 条管理记录`
      : '扫描完成：没有新增管理记录，已刷新已有清单；不代表游戏未安装 Mod。')
    emitFeedback('scan-complete', { count: imported })
    return { ok: true, imported }
  } catch (_) {
    emitFeedback('error', { source: 'scan' })
    toast('扫描未完成，不能据此判断是否安装了 Mod；请查看诊断信息。', 'error')
    return { ok: false }
  } finally {
    // Prior/background imports can already exist even when this scan adds zero.
    try { await onRefresh?.() } catch (_) { /* Keep the scan receipt truthful. */ }
  }
}
