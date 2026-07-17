import React, { useState, useEffect, useRef } from 'react'
import { Download, X, Check, AlertCircle, Loader2 } from 'lucide-react'

export default function DownloadPanel({ api }) {
  const [state, setState] = useState({ active: false, items: [], updated: 0 })
  const [dismissed, setDismissed] = useState(false)
  const wasActive = useRef(false)

  useEffect(() => {
    let timer
    const poll = async () => {
      try {
        const r = await fetch(api + '/downloads/status')
        const s = await r.json()
        setState(s)
        if (s.active && !wasActive.current) setDismissed(false) // 新一批开始 → 重新显示
        wasActive.current = s.active
      } catch (_) {}
    }
    poll()
    timer = setInterval(poll, 800)
    return () => clearInterval(timer)
  }, [api])

  const items = state.items || []
  const recent = items.length > 0 && (Date.now() / 1000 - (state.updated || 0) < 12)
  if (dismissed || items.length === 0 || (!state.active && !recent)) return null

  const done = items.filter(i => i.status === 'done').length
  const failed = items.filter(i => i.status === 'failed').length
  const finished = !state.active

  return (
    <div className="fixed bottom-4 right-4 w-80 z-40 rounded-xl border border-cyber-cyan/25 bg-surface-800/95 backdrop-blur-md shadow-2xl shadow-black/40 overflow-hidden animate-fade-in">
      <div className="flex items-center justify-between px-3 py-2 border-b border-surface-700 bg-surface-900/60">
        <div className="flex items-center gap-2 text-xs font-medium text-cyber-cyan">
          {finished ? <Download size={13} /> : <Loader2 size={13} className="animate-spin" />}
          下载队列 · {done}/{items.length}
          {failed > 0 && <span className="text-cyber-red">（{failed} 失败）</span>}
        </div>
        {finished && (
          <button onClick={() => setDismissed(true)} className="text-surface-500 hover:text-white transition-colors">
            <X size={14} />
          </button>
        )}
      </div>
      <div className="max-h-64 overflow-y-auto p-2 space-y-1.5">
        {items.map((it, i) => (
          <div key={i} className="px-2 py-1.5 rounded-md bg-surface-900/40">
            <div className="flex items-center gap-2 mb-1">
              <span className="shrink-0">
                {it.status === 'done' ? <Check size={12} className="text-cyber-green" />
                  : it.status === 'failed' ? <AlertCircle size={12} className="text-cyber-red" />
                  : it.status === 'downloading' ? <Loader2 size={12} className="text-cyber-cyan animate-spin" />
                  : <span className="block w-3 h-3 rounded-full border border-surface-500" />}
              </span>
              <span className="flex-1 truncate text-[11px] text-surface-200" title={it.name}>{it.name}</span>
              <span className="text-[10px] text-surface-500 shrink-0">
                {it.status === 'done' ? '完成' : it.status === 'failed' ? '失败' : it.status === 'downloading' ? `${it.pct}%` : '等待'}
              </span>
            </div>
            <div className="h-1 rounded-full bg-surface-700 overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-300 ${
                it.status === 'failed' ? 'bg-cyber-red' : it.status === 'done' ? 'bg-cyber-green' : 'bg-cyber-cyan'}`}
                style={{ width: `${it.status === 'done' ? 100 : it.status === 'queued' ? 6 : it.pct}%` }} />
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
