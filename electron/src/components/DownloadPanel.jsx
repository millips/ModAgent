import React, { useState, useEffect, useRef } from 'react'
import { Download, X, Check, AlertCircle, Loader2, Clock3 } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { requestLocalJson } from './localApi.mjs'
import { validateDownloadStatus, progressPercent } from './downloadStatus.mjs'

function formatDuration(value, en) {
  const seconds = Math.max(0, Math.round(Number(value) || 0))
  if (seconds < 60) return en ? `${seconds}s` : `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return en ? `${minutes}m${rest ? ` ${rest}s` : ''}` : rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

function downloadItemLabel(item, en) {
  const name = String(item?.name || '').trim() || `Mod ${item?.mod_id ?? ''}`.trim()
  const source = en && item?.source === 'workshop' ? 'Steam Workshop' : String(item?.source_label || '').trim()
  return source ? en ? `${name} (${source})` : `${name}（${source}）` : name
}

const englishPhases = {
  cache_hit: 'Using cached download', preparing: 'Checking file details',
  browser_opened: 'Nexus download page opened', browser_preparing: 'Preparing Nexus download',
  waiting_verification: 'Complete verification in the browser', verification_resolved: 'Verified; continuing',
  browser_downloading: 'Downloading in browser', browser_download_complete: 'Browser download finished',
  transferring: 'Downloading', importing: 'Importing browser download',
  verifying: 'Verifying archive', download_complete: 'Download verified',
}

export default function DownloadPanel({ api, language = 'zh-CN' }) {
  const en = language === 'en'
  const ui = (zh, english) => en ? english : zh
  const [state, setState] = useState({ active: false, items: [], updated: 0, overall_pct: 0 })
  const [dismissed, setDismissed] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [pollError, setPollError] = useState(false)
  const [cancelMessage, setCancelMessage] = useState('')
  const cancelLock = useRef(false)
  const lifetime = useRef(null)
  const previous = useRef(null)
  const startedGeneration = useRef(null)
  const verificationShown = useRef(new Set())
  const verificationEpisode = useRef(0)

  useEffect(() => {
    let timer
    const controller = new AbortController()
    lifetime.current = controller
    previous.current = null
    startedGeneration.current = null
    verificationShown.current.clear()
    setState({ active: false, items: [], updated: 0, overall_pct: 0 })
    setPollError(false)
    setCancelMessage('')
    setCancelling(false)
    cancelLock.current = false
    const poll = async () => {
      try {
        const s = await requestLocalJson(api + '/downloads/status', { signal: controller.signal })
        if (controller.signal.aborted) return
        validateDownloadStatus(s)
        setPollError(false)
        const prev = previous.current
        const generation = s.generation ?? 0
        for(const [index,item] of s.items.entries()) {
          const key=`download:${generation}:${item.mod_id??index}`
          const needsHelp=item.phase==='waiting_verification' || item.status==='waiting_verification'
          if(needsHelp && !verificationShown.current.has(key)) {
            verificationShown.current.add(key)
            setDismissed(false)
            const episodeKey=`${key}:${++verificationEpisode.current}`
            if(typeof window.modagent?.showBrowser==='function')Promise.resolve(window.modagent.showBrowser({site:item.source==='workshop'?'steam':'nexus',automatic:true,key:episodeKey})).catch(()=>{})
          }
          if(!needsHelp)verificationShown.current.delete(key)
        }
        const actualTransfer = s.items.some(item => [
          'browser_downloading', 'browser_download_complete', 'transferring',
        ].includes(item.phase))
        if (actualTransfer && startedGeneration.current !== generation) {
          startedGeneration.current = generation
          setDismissed(false)
          emitFeedback('download-start', { count: s.items.length })
        }
        if (prev && prev.generation === generation) {
          if (s.active && !prev.active) {
            setDismissed(false)
          }
          const oldItems = new Map(prev.items.map((item, index) => [String(item.mod_id ?? index), item]))
          s.items.forEach((item, index) => {
            const old = oldItems.get(String(item.mod_id ?? index))
            if (item.phase === 'waiting_verification' && old?.phase !== 'waiting_verification') {
              emitFeedback('warning', { modId: item.mod_id, name: item.name })
            }
            if (item.phase === 'verification_resolved' && old?.phase === 'waiting_verification') {
              emitFeedback('notice', { modId: item.mod_id, name: item.name })
            }
            if (item.status === 'done' && old?.status !== 'done') {
              emitFeedback('download-item-complete', { modId: item.mod_id, name: item.name })
            }
          })
          if (!s.active && prev.active && !s.cancel_requested && s.items.length > 1 && s.items.every(item => item.status === 'done')) {
            emitFeedback('download-batch-complete', { count: s.items.length })
          }
        } else if (s.active) {
          setDismissed(false)
        }
        if (prev?.generation !== generation) setCancelMessage('')
        previous.current = s
        setState(s)
      } catch (_) {
        if (!controller.signal.aborted) setPollError(true)
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 800)
      }
    }
    poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [api])

  const items = state.items || []
  // 来源对齐的结论已经在 Mod 管理页的 toast / 歧义确认面板中呈现，
  // 完成后不再像下载任务一样保留 12 秒，避免右下角出现“已结束”残影。
  const recent = !['source_align', 'update_check'].includes(state.task_kind)
    && items.length > 0
    && (Date.now() / 1000 - (state.updated || 0) < 12)
  if (!pollError && (dismissed || items.length === 0 || (!state.active && !recent))) return null

  const done = items.filter(i => ['done', 'cancelled'].includes(i.status)).length
  const failed = items.filter(i => i.status === 'failed').length
  const cancelledCount = items.filter(i => i.status === 'cancelled').length
  const finished = !state.active
  const overall = finished && items.length > 0 && items.every(item => item.status === 'done')
    ? 100 : progressPercent(state.overall_pct)
  const eta = state.eta_seconds == null ? ui('正在估算', 'Estimating') : `${ui('约 ', '~')}${formatDuration(state.eta_seconds, en)}`
  const currentPhase = state.current_item?.phase || ''
  const showEta = ['browser_downloading', 'transferring'].includes(currentPhase)
  const taskLabels = {
    source_align: [ui('来源对齐已结束', 'Source matching ended'), ui('正在对齐维护来源', 'Matching sources')],
    update_check: [ui('更新检查已结束', 'Update check ended'), ui('正在检查更新', 'Checking updates')],
    mod_update: [ui('Mod 更新已结束', 'Mod update ended'), ui('正在更新 Mod', 'Updating Mods')],
    download: [ui('下载任务已结束', 'Download task ended'), ui('正在下载', 'Downloading')],
  }
  const [finishedLabel, activeLabel] = (Object.hasOwn(taskLabels, state.task_kind) ? taskLabels[state.task_kind] : null) || [
    ui('任务已结束', 'Task ended'), ui(state.label || '正在处理', 'Processing'),
  ]
  const cancellable = state.active && [
    'source_align', 'update_check', 'mod_update', 'download',
  ].includes(state.task_kind)

  const cancelTask = async () => {
    if (cancelLock.current || state.cancel_requested || pollError || !cancellable) return
    cancelLock.current = true
    setCancelling(true)
    setCancelMessage('')
    const controller = lifetime.current
    const generation = state.generation
    const isCurrent = () => !controller.signal.aborted && previous.current?.generation === generation
    try {
      const result = await requestLocalJson(`${api}/tasks/cancel`, {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_kind: state.task_kind, generation }),
      })
      if (!isCurrent()) return
      if (result?.ok !== true) throw new Error('unconfirmed')
      setCancelMessage('TASK_CANCEL_REQUESTED')
      emitFeedback('cancel', { source: 'task-progress' })
    } catch (_) {
      if (isCurrent()) setCancelMessage('TASK_CANCEL_UNCONFIRMED')
    } finally {
      if (!controller.signal.aborted) { cancelLock.current = false; setCancelling(false) }
    }
  }

  return (
    <div className="fixed bottom-4 right-4 w-80 z-40 rounded-xl border border-cyber-cyan/25 bg-surface-800/95 backdrop-blur-md shadow-2xl shadow-black/40 overflow-hidden animate-fade-in">
      <div className="px-3 py-2.5 border-b border-surface-700 bg-surface-900/60">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-medium text-cyber-cyan min-w-0">
            {finished ? <Download size={13} /> : <Loader2 size={13} className="animate-spin shrink-0" />}
            <span className="truncate">
              {pollError ? ui('任务状态待核验', 'Task status unverified') : state.cancel_requested && state.active
                ? ui('正在取消', 'Cancelling')
                : cancelledCount && finished
                ? ui('任务已取消', 'Task cancelled')
                : finished ? finishedLabel : activeLabel} · {done}/{items.length}
            </span>
            {failed > 0 && <span className="text-cyber-red shrink-0">{failed} {ui('失败', 'failed')}</span>}
          </div>
          {cancellable ? (
            <button
              onClick={cancelTask}
              disabled={cancelling || state.cancel_requested || pollError}
              className="flex items-center gap-1 text-[10px] text-cyber-red hover:text-white disabled:opacity-50 transition-colors"
              title={ui('请求安全停止当前任务，已完成结果会保留', 'Request a safe stop; completed results are kept')}
            >
              <X size={13} /> {cancelling || state.cancel_requested ? ui('正在取消', 'Cancelling') : ui('取消', 'Cancel')}
            </button>
          ) : finished && (
            <button aria-label={ui('关闭进度面板', 'Dismiss progress panel')} onClick={() => setDismissed(true)} className="text-surface-500 hover:text-white transition-colors">
              <X size={14} />
            </button>
          )}
        </div>
        <div className="flex items-center justify-between mt-2 text-[10px] text-surface-400">
          <span>{overall.toFixed(overall % 1 ? 1 : 0)}%</span>
          <span className="flex items-center gap-1"><Clock3 size={10} />
            {ui('已用', 'Elapsed')} {formatDuration(state.elapsed_seconds, en)}
            {state.active && showEta && state.eta_seconds != null ? ` · ${ui('剩余', 'Remaining')} ${eta}` : ''}
          </span>
        </div>
        <div className="h-1.5 mt-1 rounded-full bg-surface-700 overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-500 ${failed ? 'bg-cyber-yellow' : 'bg-cyber-cyan'}`}
            style={{ width: `${Math.max(overall > 0 ? overall : 2, 2)}%` }} />
        </div>
      </div>
      {pollError && <div role="alert" className="px-3 py-2 text-xs text-cyber-yellow">[DOWNLOAD_STATUS_UNAVAILABLE] {ui('无法更新任务状态，显示的可能是旧进度。正在自动重试；不代表任务已停止。', 'Cannot update task status; progress may be stale. Retrying automatically. This does not mean the task has stopped.')}</div>}
      {cancelMessage && <div role="status" className="px-3 py-2 text-xs text-surface-300">[{cancelMessage}] {cancelMessage === 'TASK_CANCEL_REQUESTED'
        ? ui('已请求取消，后台可能仍在收尾，请等待最终状态。', 'Cancellation requested. The task may still be finishing; wait for its final state.')
        : ui('未确认取消成功；请求可能已送达，请先核对后台状态。', 'Cancellation is unconfirmed. The request may have reached the service; check the task state before retrying.')}</div>}
      <div className="max-h-64 overflow-y-auto p-2 space-y-1.5">
        {items.map((it, i) => (
          <div key={`${it.mod_id ?? 'item'}-${i}`} className="px-2 py-1.5 rounded-md bg-surface-900/40">
            <div className="flex items-center gap-2 mb-1">
              <span className="shrink-0">
                {it.status === 'done' ? <Check size={12} className="text-cyber-green" />
                  : it.status === 'failed' ? <AlertCircle size={12} className="text-cyber-red" />
                  : ['processing', 'downloading', 'waiting_verification'].includes(it.status)
                    ? <Loader2 size={12} className="text-cyber-cyan animate-spin" />
                  : <span className="block w-3 h-3 rounded-full border border-surface-500" />}
              </span>
              <span
                className="flex-1 truncate text-[11px] text-surface-200"
                title={downloadItemLabel(it, en)}
              >
                {downloadItemLabel(it, en)}
              </span>
              <span className="text-[10px] text-surface-500 shrink-0">
                {it.status === 'done' ? ui('完成', 'Done')
                  : it.status === 'failed' ? ui('失败', 'Failed')
                  : it.status === 'cancelled' ? ui('已取消', 'Cancelled')
                  : (en ? (Object.hasOwn(englishPhases, it.phase) ? englishPhases[it.phase] : '') : it.phase_label) || (it.status === 'downloading' ? `${progressPercent(it.pct)}%`
                  : it.status === 'processing' ? ui('处理中', 'Processing')
                  : it.status === 'waiting_verification' ? ui('等待验证', 'Waiting for verification')
                  : it.status === 'queued' ? ui('等待', 'Queued') : ui('状态待核验', 'Status unverified'))}
              </span>
            </div>
            <div className="h-1 rounded-full bg-surface-700 overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-300 ${
                it.status === 'failed' ? 'bg-cyber-red' : it.status === 'done' ? 'bg-cyber-green' : 'bg-cyber-cyan'}`}
                style={{ width: `${it.status === 'done' ? 100 : ['queued', 'processing', 'waiting_verification'].includes(it.status) ? 3 : progressPercent(it.pct)}%` }} />
            </div>
            {it.detail && !['done', 'failed'].includes(it.status) && (
              <div className="mt-1 text-[10px] text-surface-400 truncate" title={it.detail}>{en ? 'Service detail (original): ' : ''}{it.detail}</div>
            )}
            {it.status === 'failed' && it.error && (
              <div className="mt-1 text-[10px] text-cyber-red/80 truncate" title={it.error}>{en ? 'Service error (original): ' : ''}{it.error}</div>
            )}
            {(it.phase==='waiting_verification' || it.status==='waiting_verification') && <button type="button" className="btn-ghost mt-1 text-xs" onClick={async()=>{
              try {const result=await window.modagent?.showBrowser?.({site:it.source==='workshop'?'steam':'nexus'});if(!result?.ok)setCancelMessage(ui('未能显示浏览器，请到设置检查浏览器状态。','Could not show the browser. Check browser status in Settings.'))}catch{setCancelMessage(ui('未能显示浏览器，请到设置重试。','Could not show the browser. Retry in Settings.'))}
            }}>{ui('打开浏览器完成验证','Open browser to verify')}</button>}
          </div>
        ))}
      </div>
    </div>
  )
}
