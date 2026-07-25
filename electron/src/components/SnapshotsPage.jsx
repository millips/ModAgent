import React, { useState, useEffect } from 'react'
import { Camera, RotateCcw, Clock, Shield, Trash2, Eye, X } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'

export default function SnapshotsPage({ toast, api, status, onRefresh }) {
  const [snaps, setSnaps] = useState([])
  const [storage, setStorage] = useState(null)
  const [actionLock, setActionLock] = useState(null)
  const [preview, setPreview] = useState(null)
  const [delConfirm, setDelConfirm] = useState(null)
  const [restoreConfirm, setRestoreConfirm] = useState(null)   // 回滚预览确认弹窗数据

  useEffect(() => { loadSnaps() }, [status.game_slug, status.game_instance_id])

  const loadSnaps = async () => {
    try {
      const scope = status.game_instance_id || status.game_slug || ''
      const url = scope ? `${api}/snapshots?game_slug=${encodeURIComponent(scope)}` : `${api}/snapshots`
      const storageUrl = scope
        ? `${api}/snapshots/storage?game_slug=${encodeURIComponent(scope)}`
        : `${api}/snapshots/storage`
      const [r, storageResponse] = await Promise.all([fetch(url), fetch(storageUrl)])
      if (!r.ok) throw new Error(`snapshots request failed: ${r.status}`)
      const data = await r.json()
      if (!Array.isArray(data)) throw new Error('snapshots response is not an array')
      const storageData = storageResponse.ok ? await storageResponse.json() : null
      setStorage(storageData)
      setSnaps(data.map(s => ({
        id: s.id, time: new Date(s.timestamp * 1000).toLocaleString(),
        trigger: s.trigger_mod_name || '', files: s.files_count || 0,
        baseline: !!s.baseline, valid: s.valid !== false,
        logicalBytes: storageData?.snapshots?.[s.id]?.logical_bytes || 0,
        exclusiveBytes: storageData?.snapshots?.[s.id]?.exclusive_bytes || 0,
      })))
    } catch (_) { toast('加载快照失败', 'error') }
  }

  const formatBytes = value => {
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
    try {
      const scope = status.game_instance_id || status.game_slug || ''
      const r = await fetch(`${api}/snapshots/reconcile?game_slug=${encodeURIComponent(scope)}`, { method: 'POST' })
      const d = await r.json()
      if (d.invalid?.length) { emitFeedback('warning', { source: 'snapshot-reconcile', count: d.invalid.length }); toast(`对账完成: ${d.invalid.length}/${d.checked} 个快照已失效(磁盘文件丢失),已标灰`, 'error') }
      else { emitFeedback('notice', { source: 'snapshot-reconcile' }); toast(`对账完成: ${d.checked} 个快照全部完好`) }
      loadSnaps()
    } catch (_) { emitFeedback('error', { source: 'snapshot-reconcile' }); toast('对账失败', 'error') }
  }

  const friendlyErr = (raw) => {
    const s = String(raw || '')
    if (s.includes('not found') || s.includes('不存在')) return '快照文件已丢失'
    if (s.length > 80) return '操作失败，请重试'
    return s
  }

  const createSnap = async () => {
    if (actionLock) return
    setActionLock('create')
    toast('创建快照中...')
    try {
      const r = await fetch(api + '/tool/snapshot_create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trigger_mod_name: '手动快照' })
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) { emitFeedback('error', { source: 'snapshot' }); toast(friendlyErr(data.error), 'error') }
      else { emitFeedback('snapshot-complete', { snapshotId: data.snapshot_id }); toast('快照已创建: ' + data.snapshot_id); loadSnaps(); onRefresh?.() }
    } catch (e) { emitFeedback('error', { source: 'snapshot' }); toast('创建失败', 'error') }
    setActionLock(null)
  }

  // 第一步:拉预览(干跑),弹确认窗。所有游戏统一走预览确认,开放模式额外带告警条。
  const askRollback = async (sid) => {
    if (actionLock) return
    setActionLock(sid)
    try {
      const r = await fetch(`${api}/snapshots/${sid}/preview`)
      if (!r.ok) { emitFeedback('error', { source: 'rollback-preview' }); toast('生成回滚预览失败', 'error'); setActionLock(null); return }
      setRestoreConfirm(await r.json())
    } catch (_) { emitFeedback('error', { source: 'rollback-preview' }); toast('生成回滚预览失败', 'error') }
    setActionLock(null)
  }

  // 第二步:用户确认后真正执行
  const rollback = async (sid) => {
    setRestoreConfirm(null)
    if (actionLock) return
    setActionLock(sid)
    toast(`回滚到 ${sid}...`)
    try {
      const r = await fetch(api + '/tool/snapshot_restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_id: sid, confirmed: true, confirmation_token: restoreConfirm?.confirmation_token })
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) { emitFeedback('error', { source: 'rollback' }); toast(friendlyErr(data.error), 'error') }
      else if (!data.complete) {
        emitFeedback('warning', { source: 'rollback', snapshotId: sid })
        toast(data.warning || '回滚后复核仍有差异，未标记为完成', 'error')
      } else {
        emitFeedback('rollback-complete', { snapshotId: sid })
        toast(`已回滚并复核: 删除 ${data.deleted ?? 0} 个 · 复制还原 ${data.restored ?? 0} 个 · 原本一致 ${data.unchanged_verified ?? 0} 个`)
        if (data.warning) { emitFeedback('warning', { source: 'rollback' }); toast(data.warning, 'error') }
        if (data.mods_cleaned?.length) {
          toast(`已同步清理 ${data.mods_cleaned.length} 条被回滚 mod 的记录`)
        }
        const w = data.workshop
        if (w && !w.in_sync) {
          const bits = []
          if (w.unsubscribed?.length) bits.push(`已退订工坊 ${w.unsubscribed.length} 项`)
          if (w.resubscribed?.length) bits.push(`已重订 ${w.resubscribed.length} 项`)
          if (w.manual_unsubscribe?.length || w.manual_subscribe?.length)
            bits.push('部分需在 Steam 手动处理')
          if (bits.length) toast(`工坊订阅同步: ${bits.join(' · ')}`)
        }
      }
    } catch (e) { emitFeedback('error', { source: 'rollback' }); toast('回滚失败', 'error') }
    setActionLock(null)
  }

  const showPreview = async (sid) => {
    try {
      const r = await fetch(`${api}/snapshots/${sid}`)
      const data = await r.json()
      setPreview(data)
    } catch (_) { emitFeedback('error', { source: 'snapshot-preview' }); toast('加载详情失败', 'error') }
  }

  const deleteSnap = async (sid) => {
    setDelConfirm(null)
    setActionLock(sid)
    try {
      const previewResponse = await fetch(`${api}/snapshots/${sid}/delete-preview`)
      if (!previewResponse.ok) throw new Error('delete preview failed')
      const deletePreview = await previewResponse.json()
      const token = encodeURIComponent(deletePreview.confirmation_token || '')
      const r = await fetch(`${api}/snapshots/${sid}?confirmation_token=${token}`, { method: 'DELETE' })
      if (r.ok) { emitFeedback('remove-complete', { snapshotId: sid }); toast('快照已删除'); loadSnaps(); onRefresh?.() }
      else { emitFeedback('error', { source: 'snapshot-delete' }); toast('删除失败', 'error') }
    } catch (e) { emitFeedback('error', { source: 'snapshot-delete' }); toast('删除失败', 'error') }
    setActionLock(null)
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-600">
        <h2 className="text-base font-semibold flex items-center gap-2">
          <Camera size={16} className="text-cyber-purple" /> 快照历史
          {storage && (
            <span
              className="px-2 py-0.5 rounded text-[10px] font-normal bg-cyber-purple/10 text-cyber-purple border border-cyber-purple/25"
              title={`普通目录统计会显示 ${formatBytes(storage.logical_bytes)}；硬链接去重后的实际数据约 ${formatBytes(storage.deduplicated_bytes)}`}
            >
              实际占用约 {formatBytes(storage.deduplicated_bytes)}
            </span>
          )}
          {storage?.orphan_snapshot_count > 0 && (
            <span
              className="px-2 py-0.5 rounded text-[10px] font-normal bg-cyber-yellow/10 text-cyber-yellow border border-cyber-yellow/25"
              title="旧版本遗留在磁盘、但已不在快照账本中的目录；当前不会自动删除，以免误删尚需恢复的数据。"
            >
              磁盘残留 {storage.orphan_snapshot_count} 份
            </span>
          )}
        </h2>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={reconcile} title="校验每个快照的磁盘文件是否还在,失效的标灰并禁用回滚">
            <Eye size={14} /> 对账
          </button>
          <button className="btn-ghost" onClick={loadSnaps}><RotateCcw size={14} /> 刷新</button>
          <button className="btn-cyber flex items-center gap-1.5" onClick={createSnap}>
            <Shield size={14} /> 创建快照
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {snaps.map(snap => (
          <div key={snap.id} className={`card-cyber flex items-center justify-between animate-fade-in transition-colors ${snap.valid ? 'hover:bg-surface-700/30' : 'opacity-45'}`}>
            <div className="flex items-center gap-4">
              <div className="w-8 h-8 rounded-full bg-cyber-purple/10 flex items-center justify-center">
                <Clock size={14} className="text-cyber-purple" />
              </div>
              <div>
                <p className="text-sm font-medium text-white font-mono flex items-center gap-2">
                  {snap.id}
                  {snap.baseline && snap.valid && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30" title="原版状态,回滚到它=清空所有 mod">原版基线</span>
                  )}
                  {!snap.valid && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-cyber-red/10 text-cyber-red border border-cyber-red/30" title="磁盘上的快照文件已丢失,无法回滚。可删除此记录。">已失效</span>
                  )}
                </p>
                <p className="text-xs text-surface-500">{snap.time} · {snap.trigger}</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span
                className="text-xs text-surface-500 text-right"
                title={`本快照逻辑大小 ${formatBytes(snap.logicalBytes)}；单独删除预计释放 ${formatBytes(snap.exclusiveBytes)}。共享数据会在最后一个引用快照删除后释放。`}
              >
                {snap.baseline ? '原版' : `${snap.files} 文件`}
                <span className="block text-[10px] text-surface-600">
                  新增占用约 {formatBytes(snap.exclusiveBytes)}
                </span>
              </span>
              <button onClick={() => showPreview(snap.id)} className="btn-ghost p-1.5" title="预览" disabled={!snap.valid}>
                <Eye size={14} />
              </button>
              <button onClick={() => askRollback(snap.id)} disabled={actionLock === snap.id || !snap.valid}
                className={`btn-ghost p-1.5 ${snap.valid ? 'text-cyber-yellow' : 'text-surface-600 cursor-not-allowed'}`}
                title={snap.valid ? '回滚' : '快照文件已丢失,无法回滚'}>
                <RotateCcw size={14} />
              </button>
              <button onClick={() => setDelConfirm(snap.id)} disabled={actionLock === snap.id} className="btn-danger p-1.5" title="删除">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {snaps.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-surface-500">
            <Camera size={32} className="mb-2 opacity-30" />
            <p className="text-sm">暂无快照记录</p>
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
            <p className="text-xs text-surface-500 mb-3">{new Date(preview.timestamp * 1000).toLocaleString()} · {preview.trigger_mod_name} · {preview.files_count} 文件</p>
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
              <RotateCcw size={14} className="text-cyber-yellow" /> 回滚确认 · {restoreConfirm.snapshot_id}
            </h3>
            <p className="text-xs text-surface-500 mb-3">
              {restoreConfirm.baseline ? '回滚到原版基线 = 清空快照域内的所有 mod 文件。' : '以下是本次回滚将执行的操作,请确认。'}
            </p>
            {restoreConfirm.domain_sniffed && (
              <div className="mb-3 px-3 py-2 rounded-md bg-cyber-yellow/10 border border-cyber-yellow/30 text-xs text-cyber-yellow">
                该游戏为开放模式:快照范围由目录名自动推测(未经人工核对)。请逐条检查"将删除"清单,确认里面没有你的存档或个人文件。
              </div>
            )}
            {restoreConfirm.external_configs?.action_count > 0 && (
              <div className="rounded border border-cyber-yellow/30 bg-cyber-yellow/5 p-2 text-xs text-surface-300">
                用户配置：将处理 {restoreConfirm.external_configs.action_count} 个 Documents/AppData 配置文件
              </div>
            )}
            <div className="space-y-3">
              <div>
                <p className="text-xs font-medium text-cyber-red mb-1">将删除 {restoreConfirm.to_delete_count} 个文件(快照之后新增的)</p>
                {restoreConfirm.to_delete_count > 0 && (
                  <div className="bg-surface-900 rounded-md p-2 max-h-40 overflow-y-auto">
                    {restoreConfirm.to_delete.map((f, i) => (
                      <p key={i} className="text-[10px] text-surface-400 font-mono truncate">{f}</p>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-xs text-surface-400">
                将还原 <span className="text-cyber-cyan">{restoreConfirm.to_restore_count}</span> 个文件到快照时的内容
                {restoreConfirm.unchanged_count > 0 && <> · {restoreConfirm.unchanged_count} 个未变动(跳过)</>}
              </p>
              {restoreConfirm.missing_in_snapshot?.length > 0 && (
                <p className="text-xs text-cyber-red">
                  警告: 快照缺失 {restoreConfirm.missing_in_snapshot.length} 个文件(磁盘数据不完整),这些文件将无法还原。建议先做"对账"。
                </p>
              )}
              {restoreConfirm.workshop && (restoreConfirm.workshop.to_unsubscribe?.length > 0 || restoreConfirm.workshop.to_resubscribe?.length > 0) && (
                <p className="text-xs text-surface-400">
                  创意工坊: 将退订 {restoreConfirm.workshop.to_unsubscribe?.length || 0} 项 · 重订 {restoreConfirm.workshop.to_resubscribe?.length || 0} 项(会操作你的 Steam 账号)
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRestoreConfirm(null)} className="btn-ghost">取消</button>
              <button onClick={() => rollback(restoreConfirm.snapshot_id)}
                className="px-4 py-2 rounded-md text-sm bg-cyber-yellow/80 text-black font-medium hover:bg-cyber-yellow transition-colors">
                确认回滚
              </button>
            </div>
          </div>
        </div>
      )}

      {delConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setDelConfirm(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-sm w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-white mb-2">删除快照</h3>
            <p className="text-xs text-surface-500 mb-4">确定要删除 {delConfirm} 吗？删除后无法回滚到此状态。</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDelConfirm(null)} className="btn-ghost">取消</button>
              <button onClick={() => deleteSnap(delConfirm)} className="tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors">删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
