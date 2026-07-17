import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Send, RotateCcw, Search, RefreshCw, Zap, Shield, AlertTriangle, Plus, Trash2, PenLine, MessageSquare, PanelLeftClose, PanelLeft, Copy, Undo2, Square, Reply, Check, X, Bug } from 'lucide-react'
import PlanCard from './PlanCard'
import DebugPanel from './DebugPanel'

// 有副作用的工具(装/卸/下/改文件/动快照)。重新生成前若上一轮调用过它们,
// 弹告知式弹窗(C-1.2):副作用不重放、也不撤销,新回答基于当前文件状态生成。
const SIDE_EFFECT_TOOLS = new Set([
  'mod_install', 'mod_install_batch', 'mod_install_custom', 'mod_uninstall', 'mod_update',
  'mod_disable', 'mod_enable', 'mod_patch', 'mod_dependency_set', 'import_existing_mods',
  'snapshot_create', 'snapshot_restore', 'snapshot_delete',
  'mod_download', 'batch_download', 'download_from_url',
  'workshop_install', 'workshop_uninstall',
])

export default function ChatPage({ status, games, onGameChange, toast, api, onRefresh }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(() => sessionStorage.getItem('chat_draft') || '')
  const [loading, setLoading] = useState(false)
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [editingMsgId, setEditingMsgId] = useState(null)
  const [editDraft, setEditDraft] = useState('')
  const [expandedRaw, setExpandedRaw] = useState({})
  const toggleRaw = (id) => setExpandedRaw(prev => ({ ...prev, [id]: !prev[id] }))
  const [streamProgress, setStreamProgress] = useState(0)
  const [skeleton, setSkeleton] = useState(false)
  const [gameSearch, setGameSearch] = useState('')
  const [gameOpen, setGameOpen] = useState(false)
  const [regenNotice, setRegenNotice] = useState(null)   // C-1.2 重新生成告知弹窗
  const [devOpen, setDevOpen] = useState(false)
  const bottomRef = useRef(null)
  const abortRef = useRef(null)
  const idRef = useRef(0)
  const activeSessionRef = useRef(null)

  const mkId = () => `m${Date.now()}_${++idRef.current}`

  // 让流式回复只写入"发送时所属的会话"，切走后不串味
  useEffect(() => { activeSessionRef.current = activeSession }, [activeSession])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => { loadSessions(); setActiveSession(null); setMessages([]) }, [status.game_slug])

  const loadSessions = async () => {
    try {
      const slug = status.game_slug || ''
      const url = slug ? `${api}/sessions?game_slug=${slug}` : `${api}/sessions`
      const r = await fetch(url)
      if (!r.ok) throw new Error(`sessions request failed: ${r.status}`)
      const data = await r.json()
      if (!Array.isArray(data)) throw new Error('sessions response is not an array')
      setSessions(data)
    } catch (_) { toast('加载会话失败', 'error') }
  }

  // 把前端展示用的 messages 投影成后端可用的干净历史（仅 user/assistant）
  const buildHistory = (msgs) =>
    msgs
      .filter(m => m.role === 'user' || m.role === 'agent')
      .map(m => ({ role: m.role === 'agent' ? 'assistant' : 'user', content: m.content }))

  // 截断时把后端会话历史覆盖为指定快照
  const syncHistory = async (sid, msgs) => {
    try {
      const response = await fetch(`${api}/sessions/${sid}/messages`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: buildHistory(msgs) }),
      })
      if (!response.ok) throw new Error(`history sync failed: ${response.status}`)
      return true
    } catch (_) {
      return false
    }
  }

  const selectSession = async (s) => {
    setSkeleton(true)
    try {
      const r = await fetch(api + '/sessions/' + s.id)
      const d = await r.json()
      setActiveSession(d.id)
      // 归一化：后端存的是 assistant，前端用 agent；补上稳定 id
      const norm = (d.messages || []).map(m => ({
        id: mkId(),
        role: m.role === 'assistant' ? 'agent' : m.role,
        content: m.content,
      }))
      setMessages(norm)
    } catch (_) { toast('加载会话失败', 'error') }
    setSkeleton(false)
  }

  const newSession = async () => {
    try {
      const r = await fetch(api + '/sessions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: '新对话' }),
      })
      const d = await r.json()
      setActiveSession(d.id)
      setMessages([])
      loadSessions()
    } catch (_) { toast('创建会话失败', 'error') }
  }

  const delSession = async (sid, e) => {
    e.stopPropagation()
    await fetch(api + '/sessions/' + sid, { method: 'DELETE' })
    if (activeSession === sid) { setActiveSession(null); setMessages([]) }
    loadSessions()
    toast('会话已删除')
  }

  const renameSession = async (sid) => {
    await fetch(api + '/sessions/' + sid, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: editTitle }),
    })
    setEditingId(null)
    loadSessions()
  }

  const copyText = async (text) => {
    await navigator.clipboard.writeText(text)
    toast('已复制')
  }

  // 重新生成：截断到触发该回复的用户消息之前，重发该用户消息
  const regenerate = (msgId) => {
    if (loading) return
    const idx = messages.findIndex(m => m.id === msgId)
    if (idx < 0) return
    let uIdx = -1
    for (let k = idx; k >= 0; k--) { if (messages[k].role === 'user') { uIdx = k; break } }
    if (uIdx < 0) return
    const userText = messages[uIdx].content
    const base = messages.slice(0, uIdx)
    // C-1.2:检测被重新生成的这一轮(uIdx..idx)有无副作用型工具调用。
    // 有 → 先弹告知窗(副作用已生效、不会撤销);无 → 直接重生成,不打扰。
    const effects = []
    for (let k = uIdx + 1; k <= idx; k++) {
      const m = messages[k]
      if (m.role === 'sys' && m.kind === 'tool' && m.name && SIDE_EFFECT_TOOLS.has(m.name)) {
        effects.push(m.summary || m.name)
      }
    }
    if (effects.length) {
      setRegenNotice({ effects, userText, base })
    } else {
      sendMsg(userText, base)
    }
  }

  // 编辑用户消息
  const startEdit = (msg) => { setEditingMsgId(msg.id); setEditDraft(msg.content) }
  const cancelEdit = () => { setEditingMsgId(null); setEditDraft('') }
  const saveEdit = (msgId) => {
    if (loading) return
    const idx = messages.findIndex(m => m.id === msgId)
    if (idx < 0) return
    const text = editDraft.trim()
    setEditingMsgId(null)
    if (!text) return
    const base = messages.slice(0, idx)  // 截断到这条用户消息之前
    sendMsg(text, base)
  }

  // 撤回最后一轮
  const undoLastPair = async () => {
    if (loading) return
    const lastUserIdx = messages.findLastIndex(m => m.role === 'user')
    if (lastUserIdx < 0) return
    const truncated = messages.slice(0, lastUserIdx)
    setMessages(truncated)
    if (activeSession) await syncHistory(activeSession, truncated)
    toast('已撤回')
  }

  const stopStream = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
      toast('已停止')
    }
  }

  const sendMsg = async (overrideText, baseMessages) => {
    const text = (overrideText !== undefined && overrideText !== null) ? overrideText : input.trim()
    if (!text || loading) return
    if (overrideText === undefined || overrideText === null) { setInput(''); sessionStorage.removeItem('chat_draft') }

    let sid = activeSession
    if (!sid) {
      const r = await fetch(api + '/sessions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: text.slice(0, 20) }),
      })
      const d = await r.json()
      sid = d.id
      setActiveSession(d.id)
      loadSessions()
    }

    // 若是编辑/重新生成带来的截断，先把后端历史同步成截断后的快照
    if (baseMessages) {
      const synced = await syncHistory(sid, baseMessages)
      if (!synced) {
        toast('无法截断旧回复，重新生成已取消', 'error')
        return
      }
    }

    setStreamProgress(0)
    const userMsg = { id: mkId(), role: 'user', content: text }
    setMessages(prev => [...(baseMessages || prev), userMsg])
    setLoading(true)

    const controller = new AbortController()
    abortRef.current = controller

    const sendSid = sid
    // 仅当用户仍停留在发送时的会话才更新界面（否则后端照常保存，切回时从 DB 重载）
    const guardedSet = (updater) => { if (activeSessionRef.current === sendSid) setMessages(updater) }

    let curAgentId = null   // 当前正在流式的 agent 消息 id
    let segText = ''        // 当前段落累计文本

    try {
      const r = await fetch(api + '/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sid }),
        signal: controller.signal,
      })

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6)
          if (jsonStr === '[DONE]') continue

          try {
            const data = JSON.parse(jsonStr)
            if (data.error) {
              curAgentId = null
              guardedSet(prev => [...prev, { id: mkId(), role: 'error', content: '[ERR] ' + data.error }])
              continue
            }
            if (data.tool) {
              curAgentId = null
              const uniq = [...new Set(data.tool)]
              guardedSet(prev => [...prev, { id: mkId(), role: 'sys', kind: 'call', content: '⚙️ 调用 ' + uniq.join('、') }])
              continue
            }
            if (data.tool_result) {
              curAgentId = null
              const tr = data.tool_result
              guardedSet(prev => [...prev, {
                id: mkId(), role: 'sys', kind: 'tool',
                ok: tr.ok, name: tr.name,
                summary: tr.summary || `${tr.ok ? '✅' : '❌'} ${tr.name}`,
                raw: tr.preview || '',
              }])
              continue
            }
            if (data.done) continue
            if (data.chunk) {
              if (activeSessionRef.current === sendSid) setStreamProgress(p => p + data.chunk.length)
              if (curAgentId === null) {
                const id = mkId()
                curAgentId = id
                segText = data.chunk
                guardedSet(prev => [...prev, { id, role: 'agent', content: segText }])
              } else {
                segText += data.chunk
                const id = curAgentId
                const txt = segText
                guardedSet(prev => prev.map(m => m.id === id ? { ...m, content: txt } : m))
              }
            }
          } catch (_) {}
        }
      }

      loadSessions()
    } catch (e) {
      if (e.name === 'AbortError') { setLoading(false); abortRef.current = null; return }
      setMessages(prev => [...prev, { id: mkId(), role: 'error', content: '连接失败: ' + e.message }])
    }

    setLoading(false)
    abortRef.current = null
  }

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg() } }

  const renderMessage = (msg, i) => {
    const isAgent = msg.role === 'agent'
    const isUser = msg.role === 'user'
    const isError = msg.role === 'error'
    const isSys = msg.role === 'sys'
    const isLast = i === messages.length - 1
    const editing = editingMsgId === msg.id

    return (
      <div key={msg.id} className="group relative">
        <div
          className={`animate-fade-in max-w-[85%] px-3.5 py-2.5 rounded-lg text-sm leading-relaxed whitespace-pre-wrap break-words relative
            ${isUser
              ? 'ml-auto bg-cyber-blue/20 text-white border border-cyber-blue/20 rounded-br-sm'
              : isError
              ? 'bg-cyber-red/5 border border-cyber-red/30 text-cyber-red rounded-bl-sm'
              : isSys
              ? (msg.kind === 'tool'
                  ? 'mr-auto bg-surface-800/50 text-surface-300 text-xs border border-surface-700'
                  : 'mx-auto bg-surface-700/40 text-surface-500 text-[11px] italic border border-surface-600')
              : 'bg-surface-800 border border-surface-600 text-white rounded-bl-sm'}`}
        >
          {editing ? (
            <div className="flex flex-col gap-2">
              <textarea
                value={editDraft}
                onChange={e => setEditDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(msg.id) } if (e.key === 'Escape') cancelEdit() }}
                rows={Math.min(editDraft.split('\n').length, 6)}
                autoFocus
                className="w-full min-w-[260px] px-2 py-1.5 rounded bg-surface-900 border border-cyber-cyan/40 text-white text-sm outline-none resize-none"
              />
              <div className="flex items-center gap-1 justify-end">
                <button onClick={() => saveEdit(msg.id)} className="flex items-center gap-1 px-2 py-0.5 rounded bg-cyber-cyan/20 text-[11px] text-cyber-cyan hover:bg-cyber-cyan/30 transition-colors">
                  <Check size={10} /> 发送
                </button>
                <button onClick={cancelEdit} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/50 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 transition-colors">
                  <X size={10} /> 取消
                </button>
              </div>
            </div>
          ) : (
            isSys ? (msg.kind === 'tool' ? renderToolResult(msg) : msg.content) : isAgent ? renderContent(msg) : msg.content
          )}

          {/* 用户消息操作条 */}
          {isUser && !editing && (
            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-cyber-blue/15 opacity-0 group-hover:opacity-100 transition-opacity justify-end">
              <button onClick={() => startEdit(msg)} disabled={loading} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/40 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 disabled:opacity-30 transition-colors">
                <PenLine size={10} /> 编辑
              </button>
              <button onClick={() => copyText(msg.content)} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/40 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 transition-colors">
                <Copy size={10} /> 复制
              </button>
            </div>
          )}

          {/* Agent / 错误消息操作条 */}
          {(isAgent || isError) && !editing && !(loading && isLast) && (
            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-surface-700/50 opacity-0 group-hover:opacity-100 transition-opacity">
              {isAgent && (
                <button onClick={() => copyText(msg.content)} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/50 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 transition-colors">
                  <Copy size={10} /> 复制
                </button>
              )}
              <button onClick={() => regenerate(msg.id)} disabled={loading} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/50 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 disabled:opacity-30 transition-colors">
                <RotateCcw size={10} /> 重新生成
              </button>
              <button onClick={undoLastPair} disabled={loading} className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-700/50 text-[11px] text-surface-300 hover:text-white hover:bg-surface-600 disabled:opacity-30 transition-colors">
                <Undo2 size={10} /> 撤回
              </button>
            </div>
          )}

          {/* 仅在最后一条消息且生成中时显示停止 */}
          {loading && isLast && (isAgent || isError) && (
            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-surface-700/50">
              <button onClick={stopStream} className="flex items-center gap-1 px-2 py-0.5 rounded bg-cyber-red/20 text-[11px] text-cyber-red hover:bg-cyber-red/30 transition-colors">
                <Square size={10} /> 停止
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  const renderToolResult = (msg) => (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className={msg.ok ? 'text-cyber-green' : 'text-cyber-red'}>{msg.summary}</span>
        {msg.raw && (
          <button onClick={() => toggleRaw(msg.id)}
            className="text-[10px] text-surface-500 hover:text-cyber-cyan transition-colors shrink-0">
            {expandedRaw[msg.id] ? '收起 ▴' : '详情 ▾'}
          </button>
        )}
      </div>
      {expandedRaw[msg.id] && msg.raw && (
        <pre className="mt-1 text-[10px] text-surface-400 bg-surface-900/70 rounded p-2 max-h-56 overflow-auto whitespace-pre-wrap break-all">{msg.raw}</pre>
      )}
    </div>
  )

  const renderContent = (msg) => {
    const text = msg.content
    const parts = text.split(/(```[\s\S]*?```)/g)
    return parts.map((part, i) => {
      if (part.startsWith('```')) {
        return <pre key={i} className="bg-surface-900 rounded-md p-3 my-2 text-xs font-mono text-cyber-cyan overflow-x-auto">{part.replace(/^```\w*\n?/, '').replace(/```$/, '')}</pre>
      }
      return <div key={i}>{part.split('\n').map((l, j) => {
        if (l.match(/^(#+)\s/)) return <h3 key={j} className="text-base font-semibold mt-3 mb-1 text-white">{l.replace(/^#+\s/, '')}</h3>
        if (l.match(/^[-*]\s/)) return <li key={j} className="ml-4 text-surface-400">{l.replace(/^[-*]\s/, '')}</li>
        if (l.includes('PLAN') || l.includes('计划') || l.includes('安装计划')) return <PlanCard key={j} text={l} />
        if (l.includes('已安装') || l.includes('快照创建完成')) return <span key={j} className="text-cyber-green">{l}<br/></span>
        if (l.includes('错误') || l.includes('失败') || l.includes('ERR')) return <span key={j} className="text-cyber-red">{l}<br/></span>
        return <span key={j}>{l}<br/></span>
      })}</div>
    })
  }

  const groupSessions = () => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today.getTime() - 86400000)
    const groups = { today: [], yesterday: [], older: [] }

    for (const s of sessions) {
      const d = new Date(s.created_at * 1000)
      if (d >= today) groups.today.push(s)
      else if (d >= yesterday) groups.yesterday.push(s)
      else groups.older.push(s)
    }
    return groups
  }

  const grouped = groupSessions()

  // 单一真相源(C-1.1):"当前是哪个游戏"只在这里算一次,顶栏/下拉框/开放标记全读它。
  // 匹配鲁棒化——slug(后端权威隔离键)优先,路径归一化回退,免得后端持久化的 game_root
  // 与 detect 出的 path 因大小写/斜杠差异对不上,导致下拉框跳到第一个游戏(v0.8 老 bug)。
  const _normPath = (p) => (p || '').replace(/[\\/]+$/, '').replace(/\\/g, '/').toLowerCase()
  const currentGame = games.find(g =>
    (status.game_slug && g.slug && g.slug === status.game_slug) ||
    (status.game_root && _normPath(g.path) === _normPath(status.game_root))
  ) || null

  return (
    <div className="flex flex-1 overflow-hidden">
      {sidebarOpen && (
        <div className="w-56 min-w-[224px] bg-surface-800 border-r border-surface-600 flex flex-col">
          <div className="p-3 border-b border-surface-600">
            <button onClick={newSession} className="btn-cyber w-full flex items-center justify-center gap-2">
              <Plus size={14} /> 新对话
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-3">
            {['today', 'yesterday', 'older'].map(group => {
              const items = grouped[group]
              if (!items.length) return null
              const label = group === 'today' ? '今天' : group === 'yesterday' ? '昨天' : '更早'
              return (
                <div key={group}>
                  <div className="text-[10px] font-semibold text-surface-500 uppercase px-2 mb-1">{label}</div>
                  {items.map(s => (
                    <div key={s.id}
                      className={`group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-xs transition-all
                        ${activeSession === s.id ? 'bg-cyber-blue/15 text-cyber-cyan' : 'text-surface-400 hover:bg-surface-700 hover:text-white'}`}
                      onClick={() => selectSession(s)}>
                      <MessageSquare size={12} className="shrink-0" />
                      {editingId === s.id ? (
                        <input className="flex-1 bg-surface-700 border border-surface-500 rounded px-1 py-0.5 text-white text-xs outline-none"
                          value={editTitle} onChange={e => setEditTitle(e.target.value)}
                          onBlur={() => renameSession(s.id)} onKeyDown={e => { if (e.key==='Enter') renameSession(s.id); if (e.key==='Escape') setEditingId(null) }}
                          autoFocus onClick={e => e.stopPropagation()} />
                      ) : (
                        <span className="flex-1 truncate">{s.title || '新对话'}</span>
                      )}
                      <div className="hidden group-hover:flex items-center gap-0.5">
                        <button onClick={e => { e.stopPropagation(); setEditingId(s.id); setEditTitle(s.title||'') }} className="p-0.5 rounded hover:bg-surface-600"><PenLine size={10} /></button>
                        <button onClick={e => delSession(s.id, e)} className="p-0.5 rounded hover:bg-surface-600 text-cyber-red"><Trash2 size={10} /></button>
                      </div>
                    </div>
                  ))}
                </div>
              )
            })}
            {sessions.length === 0 && <div className="text-xs text-surface-500 text-center py-8">暂无会话记录</div>}
          </div>
        </div>
      )}

      <div className="flex-[7] flex flex-col min-w-0">
        {games.length > 0 && (
          <div className="relative z-30 flex items-center gap-3 px-3 py-2 border-b border-surface-600 bg-surface-800">
            <div className="relative">
              <input
                className="px-2 py-1 rounded text-xs bg-surface-700 border border-surface-500 text-white outline-none w-40 focus:border-cyber-cyan/50"
                placeholder={currentGame?.name || status.game || "搜索游戏..."}
                value={gameOpen ? gameSearch : ''}
                onFocus={() => setGameOpen(true)}
                onChange={e => setGameSearch(e.target.value)}
              />
              {gameOpen && (() => {
                const filtered = games.filter(g => !gameSearch || g.name.toLowerCase().includes(gameSearch.toLowerCase()))
                const stable = filtered.filter(g => g.adapted)
                const open = filtered.filter(g => !g.adapted)
                const row = (g) => (
                  <div
                    key={g.path}
                    className={`px-2 py-1 cursor-pointer text-xs hover:bg-surface-600 flex items-center justify-between gap-2 ${currentGame?.path === g.path ? 'text-cyber-cyan' : 'text-white'}`}
                    onClick={() => {
                      onGameChange(g)
                      setGameOpen(false)
                      setGameSearch('')
                    }}
                  >
                    <span className="truncate">{g.name}{g.slug ? ' (Nexus)' : ''}</span>
                    {!g.adapted && <span className="shrink-0 text-[10px] text-amber-400/80">开放</span>}
                  </div>
                )
                return (
                  <div className="absolute top-full left-0 mt-1 rounded bg-surface-700 border border-surface-600 max-h-64 overflow-y-auto w-64 z-50">
                    {stable.length > 0 && (
                      <div className="px-2 pt-1.5 pb-0.5 text-[10px] text-cyber-cyan/70 uppercase tracking-wider select-none">稳定适配</div>
                    )}
                    {stable.map(row)}
                    {open.length > 0 && (
                      <div className="px-2 pt-1.5 pb-0.5 text-[10px] text-amber-400/70 uppercase tracking-wider select-none border-t border-surface-600"
                        title="未特化适配:搜索/安装走通用规则,落位不保证,请核对结果">开放模式(实验)</div>
                    )}
                    {open.map(row)}
                  </div>
                )
              })()}
              {/* Click outside to close */}
              {gameOpen && <div className="fixed inset-0 z-40" onClick={() => { setGameOpen(false); setGameSearch('') }} />}
            </div>
            {currentGame && !currentGame.adapted && (
              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-amber-400/10 text-amber-400 border border-amber-400/30"
                title="该游戏未特化适配:搜索/安装走通用兜底规则,落位不保证;快照走目录嗅探。结果请自行核对。">
                开放模式
              </span>
            )}
            <span className="text-[11px] text-surface-500 truncate flex-1">{status.game_root}</span>
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {skeleton && (
            <div className="space-y-3 py-4">
              <div className="skeleton h-12 w-3/4 ml-auto" />
              <div className="skeleton h-16 w-2/3" />
              <div className="skeleton h-8 w-1/2" />
            </div>
          )}
          {messages.length === 0 && !skeleton && (
            <div className="flex flex-col items-center justify-center h-full text-surface-500 select-none">
              <Zap size={40} className="text-cyber-cyan/30 mb-3" />
              <p className="text-sm">用中文描述你的需求</p>
              <p className="text-xs mt-1">例如: 帮我搜一个赛博朋克的画质 mod</p>
            </div>
          )}
          {messages.map((msg, i) => renderMessage(msg, i))}
          {loading && (
            <div className="flex items-center gap-2 text-surface-500 text-sm py-2 animate-fade-in">
              <RefreshCw size={14} className="animate-spin" /> ModAgent 思考中...
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="p-3 border-t border-surface-600 bg-surface-800 flex items-end gap-2">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="btn-ghost p-2" title={sidebarOpen?'收起':'展开'}>
            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeft size={16} />}
          </button>
          <textarea value={input} onChange={e => { setInput(e.target.value); sessionStorage.setItem('chat_draft', e.target.value) }} onKeyDown={handleKey}
            placeholder="输入消息 · Enter 发送 · Shift+Enter 换行" rows={1}
            className="flex-1 px-3 py-2 rounded-md text-sm bg-surface-900 border border-surface-600 text-white placeholder-surface-500 outline-none resize-none max-h-[120px] focus:border-cyber-cyan/50 transition-colors"
            onInput={e => { e.target.style.height='auto'; e.target.style.height=Math.min(e.target.scrollHeight,120)+'px' }} />
          {loading ? (
            <button onClick={stopStream} className="tc-icon-button tc-icon-danger p-2.5 rounded-md bg-cyber-red/20 text-cyber-red border border-cyber-red/30 hover:bg-cyber-red/30 transition-all" title="停止">
              <Square size={16} />
            </button>
          ) : (
            <>
              <button onClick={() => setDevOpen(v => !v)}
                className="tc-icon-button p-1.5 rounded hover:bg-surface-700 text-surface-500" title="开发者模式">
                <Bug size={16} />
              </button>
              <button onClick={() => sendMsg()} disabled={!input.trim()}
              className="tc-icon-button p-2.5 rounded-md bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
              <Send size={16} />
            </button>
            </>
          )}
        </div>
      </div>

      <div className="flex-[3] border-l border-surface-600 bg-surface-800 p-4 flex flex-col gap-4 min-w-[220px]">
        <h3 className="text-xs font-semibold text-surface-500 uppercase tracking-wider">状态</h3>
        <div className="card-cyber"><div className="flex items-center justify-between"><span className="text-xs text-surface-500">已安装 Mod</span><span className="text-xl font-bold text-cyber-cyan">{status.mods}</span></div></div>
        <div className="card-cyber"><div className="flex items-center justify-between"><span className="text-xs text-surface-500">快照数量</span><span className="text-xl font-bold text-cyber-purple">{status.snaps}</span></div></div>
        <div className="card-cyber">
          <span className="text-xs text-surface-500 block mb-1">游戏</span>
          <select
            className="w-full px-2 py-1 rounded text-xs bg-surface-700 border border-surface-500 text-white outline-none cursor-pointer"
            value={currentGame?.path || ''}
            onChange={e => {
              const g = games.find(x => x.path === e.target.value)
              if (g) onGameChange(g)
            }}
          >
            {/* currentGame 为空 = 后端配置的游戏不在检测列表里(已卸载/移动),兜底一个 value='' 的
                option,免得 select 匹配不到时静默跳到第一个游戏、误导用户以为切换了。 */}
            {!currentGame && <option value="">{status.game ? `${status.game}(未在检测列表)` : '选择游戏...'}</option>}
            <optgroup label="稳定适配">
              {games.filter(g => g.adapted).map(g => (
                <option key={g.path} value={g.path}>{g.name}{g.slug ? ' (Nexus)' : ''}</option>
              ))}
            </optgroup>
            <optgroup label="开放模式(实验)">
              {games.filter(g => !g.adapted).map(g => (
                <option key={g.path} value={g.path}>{g.name}{g.slug ? ' (Nexus)' : ''}</option>
              ))}
            </optgroup>
          </select>
        </div>
        {loading && streamProgress > 0 && (
          <div className="card-cyber border-cyber-cyan/20">
            <div className="text-xs text-surface-500 mb-1">响应进度</div>
            <div className="w-full h-1.5 bg-surface-700 rounded-full overflow-hidden">
              <div className="h-full bg-cyber-cyan rounded-full transition-all duration-300"
                style={{ width: `${Math.min((streamProgress / 500) * 100, 100)}%` }} />
            </div>
            <div className="text-[10px] text-surface-500 mt-1">{streamProgress} 字符</div>
          </div>
        )}
        <div className="h-px bg-surface-600" />
        <h3 className="text-xs font-semibold text-surface-500 uppercase tracking-wider">快捷操作</h3>
        <button className="btn-cyber flex items-center justify-center gap-2" onClick={async () => {
          try {
            const r = await fetch(api + '/tool/mod_update_check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
            const d = await r.json()
            const data = JSON.parse(d.result || '{}')
            if (data.updates_available) toast(`发现 ${data.updates_available.length} 个可更新 Mod`)
            else toast('所有 Mod 均为最新')
          } catch (e) { toast('检查失败') }
        }}><RefreshCw size={14}/> 检查更新</button>
        <button className="btn-cyber flex items-center justify-center gap-2" onClick={async () => {
          try {
            const r = await fetch(api + '/tool/scan_existing_mods', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
            const d = await r.json()
            const data = JSON.parse(d.result || '{}')
            const identified = data.identified || []
            if (identified.length > 0) {
              toast(`已导入 ${identified.length} 个 Mod`)
              onRefresh?.()
            } else {
              toast('未检测到新 Mod')
            }
          } catch (e) { toast('扫描失败', 'error') }
        }}><Search size={14}/> 扫描已有 Mod</button>
        <button className="btn-cyber flex items-center justify-center gap-2" onClick={async () => {
          try {
            const r = await fetch(api + '/tool/snapshot_create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trigger_mod_name: '手动快照' }) })
            const d = await r.json()
            const data = JSON.parse(d.result || '{}')
            if (data.error) toast(data.error.length > 80 ? '快照创建失败' : data.error, 'error')
            else { toast('快照已创建: ' + (data.snapshot_id || '')); onRefresh?.() }
          } catch (e) { toast('快照失败', 'error') }
        }}><Shield size={14}/> 创建快照</button>
      </div>
      <DebugPanel api={api} open={devOpen} onClose={() => setDevOpen(false)} />

      {/* C-1.2:重新生成告知弹窗 —— 告知(非询问)。副作用已生效、不会被撤销;撤销走快照回滚。 */}
      {regenNotice && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setRegenNotice(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-md w-full max-h-[80vh] overflow-y-auto shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
              <RotateCcw size={14} className="text-cyber-cyan" /> 重新生成 · 上一轮的改动会保留
            </h3>
            <p className="text-xs text-surface-400 mb-3">
              上一轮执行了以下操作,它们已经生效、<span className="text-cyber-yellow">不会被这次重新生成撤销</span>:
            </p>
            <div className="bg-surface-900 rounded-md p-2 max-h-40 overflow-y-auto mb-3 space-y-1">
              {regenNotice.effects.map((e, i) => (
                <p key={i} className="text-[11px] text-surface-300 font-mono truncate">· {e}</p>
              ))}
            </div>
            <p className="text-xs text-surface-500 mb-4">
              新回答会基于<span className="text-surface-300">当前文件状态</span>重新生成。若想撤销这些改动,请到
              <span className="text-cyber-purple">快照</span>页回滚到对应的安装前快照。
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setRegenNotice(null)} className="btn-ghost">取消</button>
              <button onClick={() => { const n = regenNotice; setRegenNotice(null); sendMsg(n.userText, n.base) }}
                className="px-4 py-2 rounded-md text-sm bg-cyber-cyan/80 text-black font-medium hover:bg-cyber-cyan transition-colors">
                继续重新生成
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
