import React, { useState, useEffect, useRef } from 'react'
import { Camera, RotateCcw, Clock, Shield, Trash2, Eye, X } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { tr } from '../i18n'
import { requestLocalJson, localApiFailure, LocalApiError } from './localApi.mjs'
import { validateSnapshotReceipt } from './snapshotReceipt.mjs'
import { validateSnapshotList, validSnapshotStorage } from './snapshotList.mjs'
import { validateSnapshotPreview } from './snapshotPreview.mjs'

export default function SnapshotsPage({ toast, api, status, onRefresh, language = 'zh-CN' }) {
  const t = key => tr(language, key)
  const en = language === 'en'
  const actionRef = useRef(false)
  const scope = status.game_instance_id || status.game_slug || ''
  const scopeRef = useRef(scope)
  const scopeEpoch = useRef(0)
  if (scopeRef.current !== scope) scopeEpoch.current++
  scopeRef.current = scope
  const loadEpoch = useRef(0)
  const failure = (code, error) => toast(`[${code}] ${localApiFailure(error, language, {mutation: code.endsWith('_UNCONFIRMED') || code === 'SNAPSHOT_RECONCILE_FAILED'})}`, 'error')
  const [snaps, setSnaps] = useState([])
  const [listState, setListState] = useState({ phase: 'loading' })
  const [storage, setStorage] = useState(null)
  const [actionLock, setActionLock] = useState(null)
  const [preview, setPreview] = useState(null)
  const [delConfirm, setDelConfirm] = useState(null)
  const [restoreConfirm, setRestoreConfirm] = useState(null)   // 回滚预览确认弹窗数据

  useEffect(() => {
    setSnaps([]); setStorage(null); setPreview(null); setDelConfirm(null); setRestoreConfirm(null)
    loadSnaps()
    return () => { loadEpoch.current++ }
  }, [scope])

  const loadSnaps = async () => {
    const epoch = ++loadEpoch.current
    setListState({ phase: 'loading' }); setStorage(null)
    try {
      const scope = status.game_instance_id || status.game_slug || ''
      const url = scope ? `${api}/snapshots?game_slug=${encodeURIComponent(scope)}` : `${api}/snapshots`
      const storageUrl = scope
        ? `${api}/snapshots/storage?game_slug=${encodeURIComponent(scope)}`
        : `${api}/snapshots/storage`
      const [data, storageData] = await Promise.all([
        requestLocalJson(url), requestLocalJson(storageUrl).catch(() => null),
      ])
      if (epoch !== loadEpoch.current) return
      validateSnapshotList(data)
      const verifiedStorage = validSnapshotStorage(storageData) ? storageData : null
      setStorage(verifiedStorage)
      setSnaps(data.map(s => ({
        id: s.id, timestamp: s.timestamp,
        trigger: s.trigger_mod_name || '', files: s.files_count || 0,
        baseline: !!s.baseline, valid: s.valid !== false,
        logicalBytes: verifiedStorage && Object.hasOwn(verifiedStorage.snapshots, s.id) ? verifiedStorage.snapshots[s.id].logical_bytes : null,
        exclusiveBytes: verifiedStorage && Object.hasOwn(verifiedStorage.snapshots, s.id) ? verifiedStorage.snapshots[s.id].exclusive_bytes : null,
      })))
      setListState({ phase: 'ready' })
    } catch (error) {
      if (epoch === loadEpoch.current) setListState({ phase: 'error', error })
    }
  }

  const formatBytes = value => {
    if (value === null || value === undefined) return en ? 'unavailable' : '暂不可用'
    const bytes = Number(value || 0)
    if (bytes < 1024) return `${bytes} B`
    const units = ['KiB', 'MiB', 'GiB', 'TiB']
    let size = bytes
    let unit = -1
    do {
      size /= 1024
      unit += 1
    } while (size >= 1024 && unit < units.length - 1)
    return `${size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${units[unit]}`
  }

  const reconcile = async () => {
    if (actionRef.current) return
    actionRef.current = true; setActionLock('reconcile')
    const epoch = scopeEpoch.current
    try {
      const scope = status.game_instance_id || status.game_slug || ''
      const d = await requestLocalJson(`${api}/snapshots/reconcile?game_slug=${encodeURIComponent(scope)}`, { method: 'POST' }, {timeoutMs:120000})
      if (epoch !== scopeEpoch.current) return
      if (!Number.isInteger(d?.checked) || d.checked < 0 || !Array.isArray(d.invalid)) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      if (d.invalid?.length) { emitFeedback('warning', { source: 'snapshot-reconcile', count: d.invalid.length }); toast(en ? `Reconciled: ${d.invalid.length}/${d.checked} snapshots have missing files and are disabled.` : `对账完成: ${d.invalid.length}/${d.checked} 个快照已失效(磁盘文件丢失),已标灰`, 'error') }
      else { emitFeedback('notice', { source: 'snapshot-reconcile' }); toast(en ? `Reconciled: ${d.checked} snapshots checked; no missing snapshots reported.` : `对账完成: 已检查 ${d.checked} 个快照，未报告缺失快照。`) }
      loadSnaps()
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'snapshot-reconcile' }); failure('SNAPSHOT_RECONCILE_FAILED', error) }
    finally { actionRef.current = false; setActionLock(null) }
  }

  const friendlyErr = (raw) => {
    const s = String(raw || '')
    if (s.includes('SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE')) return en ? '[SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE] Steam subscription differences could not be checked. Restore did not start; check Steam/library access and generate a new preview.' : '[SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE] 无法核对 Steam 订阅差异，恢复尚未开始；请检查 Steam/库目录访问后重新预览。'
    if (s.includes('not found') || s.includes('不存在')) return en ? '[SNAPSHOT_MISSING] Snapshot files are missing. Reconcile snapshots before retrying.' : '[SNAPSHOT_MISSING] 快照文件已丢失，请先对账再重试。'
    return en ? '[SNAPSHOT_RESTORE_FAILED] Restore was not confirmed. Check diagnostics and current files before retrying.' : '[SNAPSHOT_RESTORE_FAILED] 回滚未确认成功，请检查诊断和当前文件后再试。'
  }

  const createSnap = async () => {
    if (actionRef.current || actionLock) return
    actionRef.current = true
    const epoch = scopeEpoch.current
    setActionLock('create')
    toast(en ? 'Creating snapshot…' : '创建快照中...')
    try {
      const d = await requestLocalJson(api + '/tool/snapshot_create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trigger_mod_name: en ? 'Manual snapshot' : '手动快照' })
      }, {timeoutMs:120000})
      if (epoch !== scopeEpoch.current) return
      let data
      try { data = JSON.parse(d.result) } catch (_) { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
      if (!data || data.error || typeof data.snapshot_id !== 'string' || !data.snapshot_id.trim()) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      emitFeedback('snapshot-complete', { snapshotId: data.snapshot_id })
      toast((en ? 'Snapshot created: ' : '快照已创建: ') + data.snapshot_id)
      if (scopeRef.current === scope) { loadSnaps(); onRefresh?.() }
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'snapshot' }); failure('SNAPSHOT_CREATE_UNCONFIRMED', error) }
    finally { actionRef.current = false; setActionLock(null) }
  }

  // 第一步:拉预览(干跑),弹确认窗。所有游戏统一走预览确认,开放模式额外带告警条。
  const askRollback = async (sid) => {
    if (actionRef.current) return
    actionRef.current = true
    const epoch = scopeEpoch.current
    setActionLock(sid)
    try {
      const data = await requestLocalJson(`${api}/snapshots/${encodeURIComponent(sid)}/preview`)
      if (epoch !== scopeEpoch.current) return
      validateSnapshotPreview(data, sid)
      setRestoreConfirm({...data, _scopeEpoch:epoch})
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'rollback-preview' }); failure('SNAPSHOT_PREVIEW_FAILED', error) }
    finally { actionRef.current = false; setActionLock(null) }
  }

  // 第二步:用户确认后真正执行
  const rollback = async (sid) => {
    if (actionRef.current || restoreConfirm?.workshop?.preview_unavailable || restoreConfirm?._scopeEpoch !== scopeEpoch.current || restoreConfirm?.snapshot_id !== sid) return
    actionRef.current = true
    const epoch = scopeEpoch.current
    setRestoreConfirm(null)
    setActionLock(sid)
    toast(en ? `Restoring ${sid}…` : `回滚到 ${sid}...`)
    try {
      const d = await requestLocalJson(api + '/tool/snapshot_restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_id: sid, confirmed: true, confirmation_token: restoreConfirm?.confirmation_token })
      }, {timeoutMs:120000})
      if (epoch !== scopeEpoch.current) return
      let data
      try { data = JSON.parse(d.result) } catch (_) { throw new LocalApiError('LOCAL_API_INVALID_RESPONSE') }
      validateSnapshotReceipt(data, sid)
      if (data.error) { emitFeedback('error', { source: 'rollback' }); toast(friendlyErr(data.error), 'error') }
      else if (!data.complete) {
        emitFeedback('warning', { source: 'rollback', snapshotId: sid })
        toast(data.audit_log_saved === false
          ? (en ? '[SNAPSHOT_RECEIPT_NOT_SAVED] The restore ran, but its history could not be saved. Check files and the Mod list and restore database access before retrying. Do not assume that nothing changed.' : '[SNAPSHOT_RECEIPT_NOT_SAVED] 回滚已执行，但操作记录未能保存。请核对文件和 Mod 清单，先恢复数据库可用性；不要当作什么都没发生而直接重试。')
          : data.inventory_cleanup?.complete === false
          ? (en ? '[SNAPSHOT_INVENTORY_PENDING] Inventory updates failed after the restore attempt. Do not assume the Mod list is current. Check diagnostics and database access, then preview and confirm the restore again.' : '[SNAPSHOT_INVENTORY_PENDING] 回滚后的库存同步失败，当前 Mod 清单可能未更新。请检查诊断和数据库可用性，再重新预览并确认回滚。')
          : (en ? '[SNAPSHOT_RESTORE_INCOMPLETE] Verification found remaining differences; restore is not complete. Check diagnostics before retrying.' : '[SNAPSHOT_RESTORE_INCOMPLETE] 回滚后复核仍有差异，未标记为完成，请检查诊断后再试。'), 'error')
      } else {
        emitFeedback('rollback-complete', { snapshotId: sid })
        toast(en ? `Restored and verified (snapshot files only): ${data.deleted} deleted · ${data.restored} restored · ${data.unchanged_verified} already matched. Steam subscriptions are reported separately.` : `快照范围内文件已回滚并复核: 删除 ${data.deleted} 个 · 复制还原 ${data.restored} 个 · 原本一致 ${data.unchanged_verified} 个。Steam 订阅状态另行报告。`)
        if (data.warning) { emitFeedback('warning', { source: 'rollback' }); toast(data.warning, 'error') }
        if (data.mods_cleaned?.length) {
          toast(en ? `Removed ${data.mods_cleaned.length} rolled-back Mod records.` : `已同步清理 ${data.mods_cleaned.length} 条被回滚 mod 的记录`)
        }
        const w = data.workshop
        if (w && !w.in_sync) {
          const bits = []
          if (w.unsubscribed?.length) bits.push(en ? `${w.unsubscribed.length} unsubscribed` : `已退订工坊 ${w.unsubscribed.length} 项`)
          if (w.resubscribed?.length) bits.push(en ? `${w.resubscribed.length} resubscribed` : `已重订 ${w.resubscribed.length} 项`)
          if (w.manual_unsubscribe?.length || w.manual_subscribe?.length) {
            bits.push(en ? 'Some items require manual action in Steam' : '部分需在 Steam 手动处理')
            toast(en ? '[SNAPSHOT_WORKSHOP_PENDING] Steam subscriptions are not fully restored. Review the subscription differences in Steam; file recovery does not confirm subscription recovery.' : '[SNAPSHOT_WORKSHOP_PENDING] Steam 订阅尚未全部恢复，请在 Steam 核对订阅差异；文件恢复不代表订阅恢复。', 'warn')
          }
          if (bits.length) toast((en ? 'Workshop subscriptions: ' : '工坊订阅同步: ') + bits.join(' · '))
        }
      }
      if (epoch === scopeEpoch.current) { loadSnaps(); onRefresh?.() }
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'rollback' }); failure('SNAPSHOT_RESTORE_UNCONFIRMED', error) }
    finally { actionRef.current = false; setActionLock(null) }
  }

  const showPreview = async (sid) => {
    const epoch = scopeEpoch.current
    try {
      const data = await requestLocalJson(`${api}/snapshots/${encodeURIComponent(sid)}`)
      if (epoch !== scopeEpoch.current) return
      if (data?.id !== sid || !Array.isArray(data.files) || data.files.some(f => typeof f !== 'string')) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      setPreview(data)
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'snapshot-preview' }); failure('SNAPSHOT_DETAIL_FAILED', error) }
  }

  const deleteSnap = async (sid) => {
    if (actionRef.current) return
    actionRef.current = true
    const epoch = scopeEpoch.current
    setDelConfirm(null)
    setActionLock(sid)
    try {
      const deletePreview = await requestLocalJson(`${api}/snapshots/${encodeURIComponent(sid)}/delete-preview`)
      if (epoch !== scopeEpoch.current) return
      if (deletePreview?.snapshot_id !== sid || typeof deletePreview.confirmation_token !== 'string' || !deletePreview.confirmation_token) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      const token = encodeURIComponent(deletePreview.confirmation_token)
      const result = await requestLocalJson(`${api}/snapshots/${encodeURIComponent(sid)}?confirmation_token=${token}`, { method: 'DELETE' }, {timeoutMs:120000})
      if (epoch !== scopeEpoch.current) return
      if (result?.ok !== true) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
      emitFeedback('remove-complete', { snapshotId: sid }); toast(en ? 'Snapshot deleted.' : '快照已删除')
      if (epoch === scopeEpoch.current) { loadSnaps(); onRefresh?.() }
    } catch (error) { if (epoch !== scopeEpoch.current) return; emitFeedback('error', { source: 'snapshot-delete' }); failure('SNAPSHOT_DELETE_UNCONFIRMED', error) }
    finally { actionRef.current = false; setActionLock(null) }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-600">
        <h2 className="text-base font-semibold flex items-center gap-2">
          <Camera size={16} className="text-cyber-purple" /> {t('snapshotHistory')}
          {storage && (
            <span
              className="px-2 py-0.5 rounded text-[10px] font-normal bg-cyber-purple/10 text-cyber-purple border border-cyber-purple/25"
              title={en ? `Logical size: ${formatBytes(storage.logical_bytes)}; deduplicated data: approximately ${formatBytes(storage.deduplicated_bytes)}` : `普通目录统计会显示 ${formatBytes(storage.logical_bytes)}；硬链接去重后的实际数据约 ${formatBytes(storage.deduplicated_bytes)}`}
            >
              {t('actualStorage')} {formatBytes(storage.deduplicated_bytes)}
            </span>
          )}
          {storage?.orphan_snapshot_count > 0 && (
            <span
              className="px-2 py-0.5 rounded text-[10px] font-normal bg-cyber-yellow/10 text-cyber-yellow border border-cyber-yellow/25"
              title={en ? 'Folders on disk without inventory records. They are not automatically deleted because they may contain recovery data.' : '旧版本遗留在磁盘、但已不在快照账本中的目录；当前不会自动删除，以免误删尚需恢复的数据。'}
            >
              {en ? 'Untracked folders: ' : '磁盘残留 '}{storage.orphan_snapshot_count}
            </span>
          )}
        </h2>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={reconcile} title={en ? 'Check snapshot availability; disable restore for missing snapshots.' : '校验每个快照的磁盘文件是否还在,失效的标灰并禁用回滚'}>
            <Eye size={14} /> {t('reconcileSnapshots')}
          </button>
          <button className="btn-ghost" disabled={listState.phase === 'loading'} onClick={loadSnaps}><RotateCcw size={14} /> {t('refreshMods')}</button>
          <button className="btn-cyber flex items-center gap-1.5" disabled={!!actionLock} onClick={createSnap}>
            <Shield size={14} /> {t('createSnapshot')}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {listState.phase === 'ready' && !storage && <p role="status" className="text-xs text-surface-500">{en ? '[SNAPSHOT_STORAGE_UNAVAILABLE] Storage estimates are unavailable. Snapshot history is still shown; refresh to check again.' : '[SNAPSHOT_STORAGE_UNAVAILABLE] 暂时无法确认存储占用，仍显示快照历史，可刷新重新检查。'}</p>}
        {listState.phase === 'loading' && <p role="status" className="text-sm text-surface-400">{en ? 'Loading snapshots…' : '正在读取快照…'}</p>}
        {listState.phase === 'error' && <div role="alert" className="card-cyber text-sm space-y-2">
          <p>[SNAPSHOT_LIST_FAILED] {localApiFailure(listState.error, language)}</p>
          <p>{en ? 'Snapshot history could not be read. This does not mean your backups are missing.' : '暂时无法读取快照历史，不代表备份已经丢失。'}</p>
          <button className="btn-ghost" onClick={loadSnaps}>{en ? 'Retry' : '重试'}</button>
        </div>}
        {listState.phase === 'ready' && snaps.map(snap => (
          <div key={snap.id} className={`card-cyber flex items-center justify-between animate-fade-in transition-colors ${snap.valid ? 'hover:bg-surface-700/30' : 'opacity-45'}`}>
            <div className="flex items-center gap-4">
              <div className="w-8 h-8 rounded-full bg-cyber-purple/10 flex items-center justify-center">
                <Clock size={14} className="text-cyber-purple" />
              </div>
              <div>
                <p className="text-sm font-medium text-white font-mono flex items-center gap-2">
                  {snap.id}
                  {snap.baseline && snap.valid && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30" title={en ? 'Baseline restore removes Mod files within the snapshot scope.' : '回滚到基线会清理快照范围内的 Mod 文件。'}>{en ? 'Baseline' : '原版基线'}</span>
                  )}
                  {!snap.valid && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-cyber-red/10 text-cyber-red border border-cyber-red/30" title={en ? 'Snapshot files are missing. Restore is unavailable; the record can be deleted.' : '磁盘上的快照文件已丢失,无法回滚。可删除此记录。'}>{en ? 'Unavailable' : '已失效'}</span>
                  )}
                </p>
                <p className="text-xs text-surface-500">{new Date(snap.timestamp * 1000).toLocaleString(en ? 'en-US' : 'zh-CN')} · {snap.trigger}</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span
                className="text-xs text-surface-500 text-right"
                title={en ? `Logical size ${formatBytes(snap.logicalBytes)}; deleting this snapshot may free ${formatBytes(snap.exclusiveBytes)}. Shared data remains until its last snapshot reference is deleted.` : `本快照逻辑大小 ${formatBytes(snap.logicalBytes)}；单独删除预计释放 ${formatBytes(snap.exclusiveBytes)}。共享数据会在最后一个引用快照删除后释放。`}
              >
                {snap.baseline ? (en ? 'Baseline' : '原版') : `${snap.files} ${en ? 'files' : '文件'}`}
                <span className="block text-[10px] text-surface-600">
                  {en ? 'Exclusive data: ~' : '新增占用约 '}{formatBytes(snap.exclusiveBytes)}
                </span>
              </span>
              <button onClick={() => showPreview(snap.id)} className="btn-ghost p-1.5" title={en ? 'Preview' : '预览'} disabled={!snap.valid}>
                <Eye size={14} />
              </button>
              <button onClick={() => askRollback(snap.id)} disabled={actionLock === snap.id || !snap.valid}
                className={`btn-ghost p-1.5 ${snap.valid ? 'text-cyber-yellow' : 'text-surface-600 cursor-not-allowed'}`}
                title={snap.valid ? (en ? 'Restore' : '回滚') : (en ? 'Snapshot files missing; cannot restore' : '快照文件已丢失,无法回滚')}>
                <RotateCcw size={14} />
              </button>
              <button onClick={() => setDelConfirm(snap.id)} disabled={actionLock === snap.id} className="btn-danger p-1.5" title={en ? 'Delete' : '删除'}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {listState.phase === 'ready' && snaps.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-surface-500">
            <Camera size={32} className="mb-2 opacity-30" />
            <p className="text-sm">{en ? 'No snapshots recorded' : '暂无快照记录'}</p>
          </div>
        )}
      </div>

      {preview && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setPreview(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white font-mono">{preview.id}</h3>
              <button onClick={() => setPreview(null)} className="p-1 rounded hover:bg-surface-700"><X size={14} /></button>
            </div>
            <p className="text-xs text-surface-500 mb-3">{new Date(preview.timestamp * 1000).toLocaleString()} · {preview.trigger_mod_name} · {preview.files_count} {en ? 'files' : '文件'}</p>
            <div className="bg-surface-900 rounded-md p-3 max-h-60 overflow-y-auto">
              {preview.files.map((f, i) => (
                <p key={i} className="text-[10px] text-surface-400 font-mono truncate">{f}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      {restoreConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setRestoreConfirm(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-white mb-1 font-mono flex items-center gap-2">
              <RotateCcw size={14} className="text-cyber-yellow" /> {en ? 'Confirm restore' : '回滚确认'} · {restoreConfirm.snapshot_id}
            </h3>
            <p className="text-xs text-surface-500 mb-3">
              {restoreConfirm.baseline ? (en ? 'Restoring the baseline removes Mod files within the snapshot scope.' : '回滚到原版基线 = 清空快照域内的所有 mod 文件。') : (en ? 'Review the changes below before confirming.' : '以下是本次回滚将执行的操作,请确认。')}
            </p>
            {restoreConfirm.domain_sniffed && (
              <div className="mb-3 px-3 py-2 rounded-md bg-cyber-yellow/10 border border-cyber-yellow/30 text-xs text-cyber-yellow">
                {en ? 'Open mode: snapshot scope was inferred from folder names, not manually verified. Review every file to be deleted and ensure no saves or personal files are included.' : '该游戏为开放模式:快照范围由目录名自动推测(未经人工核对)。请逐条检查"将删除"清单,确认里面没有你的存档或个人文件。'}
              </div>
            )}
            {restoreConfirm.external_configs?.action_count > 0 && (
              <div className="rounded border border-cyber-yellow/30 bg-cyber-yellow/5 p-2 text-xs text-surface-300">
                {en ? `User configuration: ${restoreConfirm.external_configs.action_count} Documents/AppData files will be processed.` : `用户配置：将处理 ${restoreConfirm.external_configs.action_count} 个 Documents/AppData 配置文件`}
              </div>
            )}
            <div className="space-y-3">
              {restoreConfirm.workshop?.preview_unavailable && <p role="alert" className="text-xs text-cyber-red">{en ? '[SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE] Steam subscription differences could not be checked. Restore is blocked and has not started. Cancel, check Steam/library access, then open a new preview.' : '[SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE] 无法核对 Steam 订阅差异，恢复已阻止且尚未开始。请取消、检查 Steam/库目录访问后重新预览。'}</p>}
              <div>
                <p className="text-xs font-medium text-cyber-red mb-1">{en ? `Delete ${restoreConfirm.to_delete_count} files added after the snapshot` : `将删除 ${restoreConfirm.to_delete_count} 个文件(快照之后新增的)`}</p>
                {restoreConfirm.to_delete_count > 0 && (
                  <div className="bg-surface-900 rounded-md p-2 max-h-40 overflow-y-auto">
                    {restoreConfirm.to_delete.map((f, i) => (
                      <p key={i} className="text-[10px] text-surface-400 font-mono truncate">{f}</p>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-xs text-surface-400">
                {en ? 'Restore ' : '将还原 '}<span className="text-cyber-cyan">{restoreConfirm.to_restore_count}</span>{en ? ' files to their snapshot contents' : ' 个文件到快照时的内容'}
                {restoreConfirm.unchanged_count > 0 && <> · {restoreConfirm.unchanged_count}{en ? ' unchanged (skipped)' : ' 个未变动(跳过)'}</>}
              </p>
              {restoreConfirm.missing_in_snapshot?.length > 0 && (
                <p className="text-xs text-cyber-red">
                  {en ? `Warning: ${restoreConfirm.missing_in_snapshot.length} snapshot files are missing and cannot be restored. Reconcile snapshots first.` : `警告: 快照缺失 ${restoreConfirm.missing_in_snapshot.length} 个文件(磁盘数据不完整),这些文件将无法还原。建议先做"对账"。`}
                </p>
              )}
              {restoreConfirm.workshop && (restoreConfirm.workshop.to_unsubscribe?.length > 0 || restoreConfirm.workshop.to_resubscribe?.length > 0) && (
                <p className="text-xs text-surface-400">
                  {en ? `Workshop: unsubscribe ${restoreConfirm.workshop.to_unsubscribe?.length || 0} · resubscribe ${restoreConfirm.workshop.to_resubscribe?.length || 0} (changes your Steam subscriptions)` : `创意工坊: 将退订 ${restoreConfirm.workshop.to_unsubscribe?.length || 0} 项 · 重订 ${restoreConfirm.workshop.to_resubscribe?.length || 0} 项(会操作你的 Steam 账号)`}
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRestoreConfirm(null)} className="btn-ghost">{en ? 'Cancel' : '取消'}</button>
              <button onClick={() => rollback(restoreConfirm.snapshot_id)}
                disabled={!!restoreConfirm.workshop?.preview_unavailable}
                className="px-4 py-2 rounded-md text-sm bg-cyber-yellow/80 text-black font-medium hover:bg-cyber-yellow transition-colors">
                {en ? 'Confirm restore' : '确认回滚'}
              </button>
            </div>
          </div>
        </div>
      )}

      {delConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setDelConfirm(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-sm w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-white mb-2">{en ? 'Delete snapshot' : '删除快照'}</h3>
            <p className="text-xs text-surface-500 mb-4">{en ? `Delete ${delConfirm}? You will no longer be able to restore this snapshot.` : `确定要删除 ${delConfirm} 吗？删除后无法回滚到此状态。`}</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDelConfirm(null)} className="btn-ghost">{en ? 'Cancel' : '取消'}</button>
              <button onClick={() => deleteSnap(delConfirm)} className="tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors">{en ? 'Delete' : '删除'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
