import React, { useState, useEffect, useRef } from 'react'
import { Download, X, Check, AlertCircle, Loader2, Clock3 } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'

function formatDuration(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

function downloadItemLabel(item) {
  const name = String(item?.name || '').trim() || `Mod ${item?.mod_id ?? ''}`.trim()
  const source = String(item?.source_label || '').trim()
  return source ? `${name}（${source}）` : name
}

export default function DownloadPanel({ api }) {
  const [state, setState] = useState({ active: false, items: [], updated: 0, overall_pct: 0 })
  const [dismissed, setDismissed] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const previous = useRef(null)

  useEffect(() => {
    let timer
    const poll = async () => {
      try {
        const r = await fetch(api + '/downloads/status')
        if (!r.ok) throw new Error(`download status failed: ${r.status}`)
        const s = await r.json()
        if (!s || !Array.isArray(s.items)) throw new Error('invalid download status')
        const prev = previous.current
        if (prev) {
          if (s.active && !prev.active) {
            setDismissed(false)
            emitFeedback('download-start', { count: s.items.length })
          }
          const oldItems = new Map(prev.items.map((item, index) => [String(item.mod_id ?? index), item]))
          s.items.forEach((item, index) => {
            const old = oldItems.get(String(item.mod_id ?? index))
            if (item.status === 'done' && old?.status !== 'done') {
              emitFeedback('download-item-complete', { modId: item.mod_id, name: item.name })
            }
          })
          if (!s.active && prev.active && s.items.length > 1 && !s.items.some(item => item.status === 'failed')) {
            emitFeedback('download-batch-complete', { count: s.items.length })
          }
        } else if (s.active) {
          setDismissed(false)
          emitFeedback('download-start', { count: s.items.length })
        }
        previous.current = s
        setState(s)
        if (!s.active || !s.cancel_requested) setCancelling(false)
      } catch (_) {}
    }
    poll()
    timer = setInterval(poll, 800)
    return () => clearInterval(timer)
  }, [api])

  const items = state.items || []
  const recent = items.length > 0 && (Date.now() / 1000 - (state.updated || 0) < 12)
  if (dismissed || items.length === 0 || (!state.active && !recent)) return null

  const done = items.filter(i => ['done', 'cancelled'].includes(i.status)).length
  const failed = items.filter(i => i.status === 'failed').length
  const cancelledCount = items.filter(i => i.status === 'cancelled').length
  const finished = !state.active
  const overall = finished && !failed && !cancelledCount
    ? 100 : Math.max(0, Math.min(100, Number(state.overall_pct) || 0))
  const eta = state.eta_seconds == null ? '正在估算' : `约 ${formatDuration(state.eta_seconds)}`
  const taskLabels = {
    source_align: ['来源对齐已结束', '正在对齐维护来源'],
    update_check: ['更新检查已结束', '正在检查更新'],
    mod_update: ['Mod 更新已结束', '正在更新 Mod'],
    download: ['下载任务已结束', '正在下载'],
  }
  const [finishedLabel, activeLabel] = taskLabels[state.task_kind] || [
    '任务已结束', state.label || '正在处理',
  ]
  const cancellable = state.active && [
    'source_align', 'update_check', 'mod_update', 'download',
  ].includes(state.task_kind)

  const cancelTask = async () => {
    if (cancelling || !cancellable) return
    setCancelling(true)
    try {
      await fetch(`${api}/tasks/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_kind: state.task_kind }),
      })
      emitFeedback('cancel', { source: 'task-progress' })
    } catch (_) {
      setCancelling(false)
    }
  }

  return (
    <div className="fixed bottom-4 right-4 w-80 z-40 rounded-xl border border-cyber-cyan/25 bg-surface-800/95 backdrop-blur-md shadow-2xl shadow-black/40 overflow-hidden animate-fade-in">
      <div className="px-3 py-2.5 border-b border-surface-700 bg-surface-900/60">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-medium text-cyber-cyan min-w-0">
            {finished ? <Download size={13} /> : <Loader2 size={13} className="animate-spin shrink-0" />}
            <span className="truncate">
              {state.cancel_requested
                ? '正在取消'
                : cancelledCount && finished
                ? '任务已取消'
                : finished ? finishedLabel : activeLabel} · {done}/{items.length}
            </span>
            {failed > 0 && <span className="text-cyber-red shrink-0">{failed} 失败</span>}
          </div>
          {cancellable ? (
            <button
              onClick={cancelTask}
              disabled={cancelling}
              className="flex items-center gap-1 text-[10px] text-cyber-red hover:text-white disabled:opacity-50 transition-colors"
              title="安全停止当前任务，已完成结果会保留"
            >
              <X size={13} /> {cancelling || state.cancel_requested ? '正在取消' : '取消'}
            </button>
          ) : finished && (
            <button onClick={() => setDismissed(true)} className="text-surface-500 hover:text-white transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
        <div className="flex items-center justify-between mt-2 text-[10px] text-surface-400">
          <span>{overall.toFixed(overall % 1 ? 1 : 0)}%</span>
          <span className="flex items-center gap-1"><Clock3 size={10} />
            已用 {formatDuration(state.elapsed_seconds)}
            {state.active && state.eta_seconds != null ? ` · 剩余 ${eta}` : ''}
          </span>
        </div>
        <div className="h-1.5 mt-1 rounded-full bg-surface-700 overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-500 ${failed ? 'bg-cyber-yellow' : 'bg-cyber-cyan'}`}
            style={{ width: `${Math.max(overall > 0 ? overall : 2, 2)}%` }} />
        </div>
      </div>
      <div className="max-h-64 overflow-y-auto p-2 space-y-1.5">
        {items.map((it, i) => (
          <div key={`${it.mod_id ?? 'item'}-${i}`} className="px-2 py-1.5 rounded-md bg-surface-900/40">
            <div className="flex items-center gap-2 mb-1">
              <span className="shrink-0">
                {it.status === 'done' ? <Check size={12} className="text-cyber-green" />
                  : it.status === 'failed' ? <AlertCircle size={12} className="text-cyber-red" />
                  : ['processing', 'downloading'].includes(it.status) ? <Loader2 size={12} className="text-cyber-cyan animate-spin" />
                  : <span className="block w-3 h-3 rounded-full border border-surface-500" />}
              </span>
              <span
                className="flex-1 truncate text-[11px] text-surface-200"
                title={downloadItemLabel(it)}
              >
                {downloadItemLabel(it)}
              </span>
              <span className="text-[10px] text-surface-500 shrink-0">
                {it.status === 'done' ? '完成'
                  : it.status === 'failed' ? '失败'
                  : it.status === 'cancelled' ? '已取消'
                  : it.status === 'downloading' ? `${it.pct}%`
                  : it.status === 'processing' ? '处理中'
                  : '等待'}
              </span>
            </div>
            <div className="h-1 rounded-full bg-surface-700 overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-300 ${
                it.status === 'failed' ? 'bg-cyber-red' : it.status === 'done' ? 'bg-cyber-green' : 'bg-cyber-cyan'}`}
                style={{ width: `${it.status === 'done' ? 100 : ['queued', 'processing'].includes(it.status) ? 3 : it.pct}%` }} />
            </div>
            {it.status === 'failed' && it.error && (
              <div className="mt-1 text-[10px] text-cyber-red/80 truncate" title={it.error}>{it.error}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
