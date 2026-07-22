import React, { useState, useEffect, useCallback, useRef } from 'react'
import { X, RefreshCw, Play, Repeat, ChevronRight, ChevronDown, Terminal, Activity, Wrench, History } from 'lucide-react'

// 开发者模式面板:自包含,靠轮询 /debug/* 工作,和聊天主流程解耦。
// props: api(基址), open(是否显示), onClose()
export default function DebugPanel({ api, open, onClose }) {
  const [enabled, setEnabled] = useState(null)     // dev_mode 是否开启
  const [tab, setTab] = useState('timeline')       // timeline | tools | history | sandbox
  const [turn, setTurn] = useState(null)
  const [expanded, setExpanded] = useState({})     // 工具行展开
  const [auto, setAuto] = useState(true)
  const timer = useRef(null)

  // sandbox
  const [sbName, setSbName] = useState('snapshot_list')
  const [sbArgs, setSbArgs] = useState('{}')
  const [sbResult, setSbResult] = useState(null)
  const [sbBusy, setSbBusy] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(api + '/debug/status')
      const d = await r.json()
      setEnabled(!!d.dev_mode)
      return !!d.dev_mode
    } catch (_) { setEnabled(false); return false }
  }, [api])

  const fetchLast = useCallback(async () => {
    try {
      const r = await fetch(api + '/debug/last_turn')
      if (!r.ok) return
      const d = await r.json()
      if (d && d.turn_id) setTurn(d)
    } catch (_) {}
  }, [api])

  useEffect(() => {
    if (!open) { if (timer.current) clearInterval(timer.current); return }
    fetchStatus().then(ok => {
      if (ok) fetchLast()
    })
  }, [open, fetchStatus, fetchLast])

  useEffect(() => {
    if (!open || !enabled || !auto) { if (timer.current) clearInterval(timer.current); return }
    timer.current = setInterval(fetchLast, 1200)
    return () => timer.current && clearInterval(timer.current)
  }, [open, enabled, auto, fetchLast])

  const runSandbox = async () => {
    setSbBusy(true); setSbResult(null)
    let parsed
    try { parsed = JSON.parse(sbArgs || '{}') }
    catch (_) { setSbResult({ error: 'args 不是合法 JSON' }); setSbBusy(false); return }
    try {
      const r = await fetch(api + '/debug/exec', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: sbName.trim(), args: parsed }),
      })
      setSbResult(await r.json())
    } catch (e) { setSbResult({ error: String(e) }) }
    setSbBusy(false)
    fetchLast()
  }

  const replay = async (overrideMsg) => {
    if (!turn) return
    try {
      const r = await fetch(api + '/debug/replay', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turn_id: turn.turn_id, message: overrideMsg ?? null }),
      })
      const d = await r.json()
      if (d.new_turn) setTurn(d.new_turn)
    } catch (_) {}
  }

  const toSandbox = (t) => {
    setSbName(t.name)
    setSbArgs(JSON.stringify(t.args || {}, null, 2))
    setTab('sandbox')
  }

  if (!open) return null

  const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleTimeString() : ''
  const dur = (turn && turn.finished_at && turn.started_at)
    ? ((turn.finished_at - turn.started_at) * 1000).toFixed(0) + 'ms' : '进行中'

  return (
    <div className="fixed right-0 top-0 h-full w-[440px] bg-surface-800 border-l border-surface-600 shadow-2xl z-50 flex flex-col text-sm">
      {/* header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-600">
        <Terminal size={16} className="text-cyber-cyan" />
        <span className="font-bold text-cyber-cyan">开发者模式</span>
        {enabled === false && <span className="text-xs text-cyber-red ml-2">未开启</span>}
        <button onClick={() => { setAuto(a => !a) }}
          className={`ml-auto p-1 rounded hover:bg-surface-700 ${auto ? 'text-cyber-green' : 'text-surface-500'}`}
          title={auto ? '自动刷新中' : '已暂停'}>
          <RefreshCw size={13} className={auto ? 'animate-spin' : ''} />
        </button>
        <button onClick={onClose} className="p-1 rounded hover:bg-surface-700 text-surface-500"><X size={15} /></button>
      </div>

      {enabled === false ? (
        <div className="p-6 text-surface-400 text-xs leading-relaxed">
          开发者模式未开启。到「设置」把 <code className="text-cyber-cyan">dev_mode</code> 打开,
          或直接改 <code>~/.modagent/config.json</code>,重启后端后再试。
        </div>
      ) : (
        <>
          {/* current turn bar */}
          <div className="px-4 py-2 border-b border-surface-600 flex items-center gap-2 text-xs text-surface-400">
            {turn ? (
              <>
                <span className="truncate max-w-[180px] text-white" title={turn.user_msg}>“{turn.user_msg}”</span>
                <span className="text-surface-500">· {turn.tools?.length || 0} 工具 · {dur}</span>
                <button onClick={() => replay(null)} className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700 hover:bg-surface-600 text-cyber-cyan" title="用同样输入重放这一轮">
                  <Repeat size={11} /> 重放
                </button>
              </>
            ) : <span>暂无轮次,先在对话里发一条消息</span>}
          </div>

          {/* tabs */}
          <div className="flex border-b border-surface-600 text-xs">
            {[['timeline', '时间线', Activity], ['tools', '工具', Wrench], ['history', 'History', History], ['sandbox', '沙箱', Play]].map(([id, label, Icon]) => (
              <button key={id} onClick={() => setTab(id)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 transition-colors
                  ${tab === id ? 'text-cyber-cyan border-b-2 border-cyber-cyan bg-surface-800/50' : 'text-surface-500 hover:text-white'}`}>
                <Icon size={12} /> {label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {/* 时间线 */}
            {tab === 'timeline' && (
              <div className="space-y-1">
                {(turn?.events || []).map((e, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="text-surface-600 shrink-0 w-16">{fmtTime(e.ts)}</span>
                    <span className={`shrink-0 w-20 font-mono ${
                      e.kind === 'tool' ? 'text-cyber-yellow' :
                      e.kind === 'tool_result' ? 'text-cyber-green' :
                      e.kind === 'error' ? 'text-cyber-red' :
                      e.kind === 'chunk' ? 'text-cyber-cyan' : 'text-surface-500'}`}>{e.kind}</span>
                    <span className="text-surface-300 break-all">{typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload)}</span>
                  </div>
                ))}
                {(!turn?.events || turn.events.length === 0) && <Empty />}
              </div>
            )}

            {/* 工具 trace */}
            {tab === 'tools' && (
              <div className="space-y-1.5">
                {(turn?.tools || []).map((t, i) => {
                  const open2 = expanded[i]
                  return (
                    <div key={i} className="border border-surface-600 rounded overflow-hidden">
                      <button onClick={() => setExpanded(p => ({ ...p, [i]: !p[i] }))}
                        className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-surface-800 text-left">
                        {open2 ? <ChevronDown size={13} className="text-surface-500 shrink-0" /> : <ChevronRight size={13} className="text-surface-500 shrink-0" />}
                        <span className={t.ok ? 'text-cyber-green' : 'text-cyber-red'}>{t.ok ? '✓' : '✗'}</span>
                        <span className="font-mono text-cyber-cyan text-xs">{t.name}</span>
                        <span className="ml-auto text-surface-600 text-[11px]">{t.ms}ms</span>
                        <span onClick={(ev) => { ev.stopPropagation(); toSandbox(t) }}
                          className="text-surface-500 hover:text-cyber-cyan p-0.5" title="复制到沙箱改参数重跑"><Wrench size={11} /></span>
                      </button>
                      {open2 && (
                        <div className="px-3 py-2 bg-black/30 border-t border-surface-600 space-y-2">
                          <Field label="args"><pre className="text-[11px] text-surface-300 whitespace-pre-wrap break-all">{JSON.stringify(t.args, null, 2)}</pre></Field>
                          <Field label="result"><pre className="text-[11px] text-surface-300 whitespace-pre-wrap break-all max-h-60 overflow-y-auto">{t.result}</pre></Field>
                        </div>
                      )}
                    </div>
                  )
                })}
                {(!turn?.tools || turn.tools.length === 0) && <Empty />}
              </div>
            )}

            {/* history dump */}
            {tab === 'history' && (
              <pre className="text-[11px] text-surface-300 whitespace-pre-wrap break-all">
                {turn?.history_after ? JSON.stringify(turn.history_after, null, 2) : ''}
              </pre>
            )}
            {tab === 'history' && !turn?.history_after && <Empty />}

            {/* 工具沙箱 */}
            {tab === 'sandbox' && (
              <div className="space-y-2">
                <Field label="工具名">
                  <input value={sbName} onChange={e => setSbName(e.target.value)}
                    className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono text-white focus:border-cyber-cyan outline-none" />
                </Field>
                <Field label="args (JSON)">
                  <textarea value={sbArgs} onChange={e => setSbArgs(e.target.value)} rows={5}
                    className="w-full bg-surface-800 border border-surface-600 rounded px-2 py-1 text-xs font-mono text-white focus:border-cyber-cyan outline-none resize-y" />
                </Field>
                <button onClick={runSandbox} disabled={sbBusy}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-cyber-blue/20 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-blue/30 disabled:opacity-50 text-xs">
                  <Play size={12} /> {sbBusy ? '执行中…' : '执行'}
                </button>
                <p className="text-[11px] text-cyber-yellow/80">⚠️ 会真实执行,可能下载或写入游戏目录。</p>
                {sbResult && (
                  <Field label="返回">
                    <pre className="text-[11px] text-surface-300 whitespace-pre-wrap break-all max-h-72 overflow-y-auto bg-black/30 rounded p-2 border border-surface-600">
                      {JSON.stringify(sbResult, null, 2)}
                    </pre>
                  </Field>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-surface-600 mb-0.5">{label}</div>
      {children}
    </div>
  )
}

function Empty() {
  return <div className="text-center text-surface-600 text-xs py-8">暂无数据</div>
}
