import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Send, RotateCcw, Search, RefreshCw, Zap, Shield, AlertTriangle, Plus, Trash2, PenLine, MessageSquare, PanelLeftClose, PanelLeft, Copy, Undo2, Square, Reply, Check, X, Bug, FolderPlus, FolderOpen, FileType2, Clock3 } from 'lucide-react'
import PlanCard from './PlanCard'
import DebugPanel from './DebugPanel'
import { getManualActionQuickReply } from './chatQuickReplies.mjs'
import { hasSameRecommendation } from './recommendationRecovery.mjs'
import { emitFeedback, emitToolFeedback, emitToolStartFeedback } from '../feedback/feedbackBus'
import { ChatEditionMessage } from '@edition'

// 有副作用的工具(装/卸/下/改文件/动快照)。重新生成时把已完成项传给后端；
// 后端强制只读生成，副作用不重放、也不撤销。
const SIDE_EFFECT_TOOLS = new Set([
  'mod_install', 'mod_install_batch', 'mod_install_custom', 'mod_uninstall', 'mod_update',
  'mod_source_bind',
  'mod_disable', 'mod_enable', 'mod_patch', 'mod_dependency_set', 'import_existing_mods',
  'game_config_write',
  'snapshot_create', 'snapshot_restore', 'snapshot_delete',
  'mod_download', 'batch_download', 'download_from_url',
  'workshop_install', 'workshop_uninstall',
])

// 面向普通用户隐藏低层网页侦察与只读校验。完整轨迹仍保存在会话数据库和
// 开发者面板；聊天区只展示下载/安装/快照等用户关心的阶段动作。
const QUIET_TOOLS = new Set([
  'browser_pages', 'browser_observe', 'browser_click', 'browser_input',
  'browser_wait', 'browser_open', 'browser_doctor',
  'nexus_get_detail', 'list_downloads', 'list_local_mods',
  'conflict_check', 'game_file_check', 'stardew_smapi_status', 'get_installed', 'read_readme',
])

const TOOL_LABELS = {
  nexus_search: '搜索 Nexus', nexus_get_detail: '核验 Mod 详情',
  mod_recommend: '分析推荐结果',
  mod_source_bind: '确认 Mod 维护来源',
  browser_open: '打开下载页面', browser_observe: '识别页面状态',
  browser_click: '操作下载页面', browser_input: '填写页面信息', browser_wait: '等待页面响应',
  conflict_check: '检查冲突与落位', game_file_check: '检查游戏文件', game_config_write: '写入游戏配置',
  stardew_smapi_status: '验收 SMAPI 启动状态',
  get_installed: '读取已安装 Mod', list_downloads: '检查下载缓存',
  list_local_mods: '检查本地 Mod', scan_existing_mods: '扫描已有 Mod',
  mod_update_check: '检查可用更新', import_existing_mods: '绑定已有 Mod',
  snapshot_create: '创建安全快照', snapshot_restore: '回滚快照',
  batch_download: '批量下载', mod_download: '下载 Mod',
  mod_install_batch: '批量安装', mod_install: '安装 Mod',
  mod_install_custom: '安装自定义 Mod', mod_uninstall: '卸载 Mod',
  mod_update: '更新 Mod', mod_disable: '禁用 Mod', mod_enable: '启用 Mod',
}

const TOOL_STAGE_SECONDS = {
  nexus_search: 15, nexus_get_detail: 10, mod_recommend: 18,
  browser_open: 12, browser_observe: 8, browser_click: 10, browser_wait: 15,
  mod_download: 45, batch_download: 90, download_from_url: 45,
  snapshot_create: 12, snapshot_restore: 25,
  mod_install: 35, mod_install_batch: 75, mod_install_custom: 40,
  scan_existing_mods: 25, get_installed: 10, mod_update_check: 35,
  conflict_check: 12, game_file_check: 15, stardew_smapi_status: 8, game_config_write: 8,
}

const RECOMMENDATION_ANCHOR_MARKER = '请在下方清单中调整选择'

function textMessageCount(messages) {
  return messages.filter(message =>
    message.role === 'user' || message.role === 'agent'
  ).length
}

function insertRecommendationAtAnchor(messages, payload, createId) {
  const card = { id: createId(), role: 'edition', payload }
  const requested = Number(payload?.anchor_after_text_count)
  let insertAt = -1

  if (Number.isInteger(requested) && requested >= 0) {
    let seen = 0
    for (let index = 0; index < messages.length; index += 1) {
      if (messages[index].role === 'user' || messages[index].role === 'agent') seen += 1
      if (seen >= requested) {
        insertAt = index + 1
        break
      }
    }
    if (requested === 0) insertAt = 0
  }

  // Migration path for recommendation states saved before positional anchors
  // existed. Their companion assistant message contains this stable footer.
  if (insertAt < 0) {
    const markerIndex = messages.findIndex(message =>
      message.role === 'agent'
      && String(message.content || '').includes(RECOMMENDATION_ANCHOR_MARKER)
    )
    if (markerIndex >= 0) insertAt = markerIndex + 1
  }

  if (insertAt < 0) return [...messages, card]
  const result = [...messages]
  result.splice(insertAt, 0, card)
  return result
}

function mergeRecommendationUpdate(messages, payload, createId) {
  const updatedKeys = new Set(
    (payload?.items || []).map(item => item?.selection_key).filter(Boolean)
  )
  let matchIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role !== 'edition') continue
    if ((message.payload?.items || []).some(
      item => updatedKeys.has(item?.selection_key)
    )) {
      matchIndex = index
      break
    }
  }
  if (matchIndex < 0) {
    return insertRecommendationAtAnchor(messages, payload, createId)
  }
  return messages.map((message, index) => (
    index === matchIndex ? { ...message, payload } : message
  ))
}

function formatProgressTime(value) {
  const seconds = Math.max(0, Number(value) || 0)
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

function ActiveTaskProgress({ task }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(timer)
  }, [task?.startedAt])
  if (!task) return null
  const elapsed = Math.max(0, (now - task.startedAt) / 1000)
  const stageElapsed = Math.max(0, (now - task.stageStartedAt) / 1000)
  const actual = task.mode === 'determinate'
  const pct = Math.max(0, Math.min(100, Number(task.pct) || 0))
  let estimated = '任务仍在进行，可随时停止'
  if (task.etaSeconds != null) {
    // Download progress has real byte counts and speed, so a remaining-time
    // estimate is meaningful here.
    estimated = `按当前速度约剩 ${formatProgressTime(task.etaSeconds)}`
  } else if (task.expectedSeconds) {
    // Search, browser and LLM stages have no trustworthy throughput signal.
    // Keep the heuristic internal and only use it to explain a long wait.
    estimated = stageElapsed > Math.max(30, task.expectedSeconds * 1.8)
      ? '外部响应较慢，任务仍在进行'
      : '正在处理，可随时停止'
  }

  return (
    <div className="mx-auto w-full max-w-2xl rounded-xl border border-cyber-cyan/25 bg-surface-800/75 backdrop-blur-sm px-3.5 py-3 animate-fade-in">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="flex items-center gap-2 text-cyber-cyan min-w-0">
          <RefreshCw size={13} className="animate-spin shrink-0" />
          <span className="truncate">{task.label || '正在处理任务'}</span>
        </span>
        <span className="text-surface-300 tabular-nums shrink-0">{actual ? `${pct.toFixed(pct % 1 ? 1 : 0)}%` : '处理中'}</span>
      </div>
      <div className="h-1.5 mt-2 rounded-full bg-surface-700 overflow-hidden">
        {actual ? (
          <div className="h-full rounded-full bg-cyber-cyan transition-all duration-500" style={{ width: `${Math.max(2, pct)}%` }} />
        ) : (
          <div className="h-full w-2/5 rounded-full bg-gradient-to-r from-cyber-cyan/20 via-cyber-cyan to-cyber-cyan/20 animate-pulse" />
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-surface-500">
        <span className="flex items-center gap-1"><Clock3 size={10} /> 已用 {formatProgressTime(elapsed)}</span>
        <span>{estimated}</span>
      </div>
    </div>
  )
}

const UPDATE_STATUS = {
  update_available: ['可更新', 'text-cyber-yellow'],
  version_unknown: ['本地版本未知 · 可同步', 'text-cyber-purple'],
  up_to_date: ['已是最新版', 'text-cyber-green'],
  managed_externally: ['Steam 托管更新', 'text-cyber-cyan'],
  unbound: ['未绑定维护页', 'text-surface-500'],
  check_failed: ['检查失败', 'text-cyber-red'],
  local_newer: ['本地版本较新', 'text-cyber-purple'],
}

function UpdateReportCard({ payload, api, toast, onRefresh }) {
  const initialItems = Array.isArray(payload?.items) ? payload.items : []
  const [items, setItems] = useState(initialItems)
  const [selected, setSelected] = useState(() => new Set(
    initialItems
      .filter(item => item.can_update && item.status === 'update_available')
      .map(item => String(item.mod_id))
  ))
  const [running, setRunning] = useState(false)

  const selectable = items.filter(item => item.can_update && !['synced', 'syncing'].includes(item.ui_status))
  const toggle = modId => {
    setSelected(current => {
      const next = new Set(current)
      const key = String(modId)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const syncSelected = async () => {
    const ids = [...selected]
    if (!ids.length || running) return
    setRunning(true)
    let succeeded = 0
    for (const modId of ids) {
      setItems(current => current.map(item => String(item.mod_id) === modId
        ? { ...item, ui_status: 'syncing', ui_message: '正在下载、建立快照并更新…' }
        : item))
      try {
        const response = await fetch(`${api}/tool/mod_update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: modId }),
        })
        const envelope = await response.json()
        const result = JSON.parse(envelope.result || '{}')
        if (result.error) throw new Error(result.error)
        succeeded += 1
        setItems(current => current.map(item => String(item.mod_id) === modId
          ? {
              ...item,
              current: result.version || item.latest,
              status: 'up_to_date',
              can_update: false,
              ui_status: 'synced',
              ui_message: `已同步至 ${result.version || item.latest}`,
            }
          : item))
        emitFeedback('install-complete', { source: 'update-report', name: result.updated || modId })
      } catch (error) {
        setItems(current => current.map(item => String(item.mod_id) === modId
          ? { ...item, ui_status: 'failed', ui_message: error.message || '更新失败' }
          : item))
        emitFeedback('error', { source: 'update-report', modId })
      }
    }
    setSelected(new Set())
    setRunning(false)
    onRefresh?.()
    toast(`同步完成：${succeeded}/${ids.length} 项成功`, succeeded === ids.length ? undefined : 'error')
  }

  const alignment = payload?.alignment?.summary || {}
  return (
    <section className="update-report-panel w-full overflow-hidden rounded-xl border border-cyber-cyan/25 bg-surface-900/90">
      <header className="update-report-header flex flex-wrap items-start justify-between gap-3 border-b border-surface-700 px-4 py-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
            <RefreshCw size={15} className="text-cyber-cyan" /> Mod 来源对齐与更新报告
          </h3>
          <p className="mt-1 text-[11px] text-surface-500">
            已绑定 {alignment.bound ?? payload?.summary?.bound ?? 0} ·
            歧义 {alignment.ambiguous ?? 0} ·
            未绑定 {payload?.summary?.unbound ?? alignment.unmatched ?? 0} ·
            检查失败 {payload?.summary?.check_failed ?? 0}
          </p>
        </div>
        <span className="rounded-full border border-cyber-cyan/20 bg-cyber-cyan/10 px-2.5 py-1 text-[10px] text-cyber-cyan">
          {items.length} 项
        </span>
      </header>
      <div className="max-h-[430px] overflow-auto">
        <table className="w-full min-w-[780px] table-fixed text-left text-xs">
          <thead className="sticky top-0 z-10 bg-surface-800 text-[10px] text-surface-500">
            <tr>
              <th className="w-12 px-3 py-2 text-center">选择</th>
              <th className="w-[28%] px-3 py-2">Mod</th>
              <th className="w-[19%] px-3 py-2">本地 / 最新</th>
              <th className="w-[18%] px-3 py-2">维护来源</th>
              <th className="px-3 py-2">状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/70">
            {items.map(item => {
              const key = String(item.mod_id)
              const checked = selected.has(key)
              const label = UPDATE_STATUS[item.status] || [item.status || '未知', 'text-surface-500']
              return (
                <tr key={key} className={checked ? 'bg-cyber-cyan/[0.045]' : ''}>
                  <td className="px-3 py-3 text-center">
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      disabled={!item.can_update || running}
                      onClick={() => toggle(key)}
                      className={`mx-auto flex h-5 w-5 items-center justify-center rounded border ${
                        checked ? 'border-cyber-cyan bg-cyber-cyan text-black' : 'border-surface-500 text-transparent'
                      } disabled:cursor-not-allowed disabled:opacity-30`}
                    >
                      <Check size={13} strokeWidth={3} />
                    </button>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="font-medium text-white">{item.name}</p>
                    <p className="mt-1 font-mono text-[9px] text-surface-500">{key}</p>
                  </td>
                  <td className="px-3 py-3 align-top font-mono text-[11px]">
                    <p>{item.current || 'unknown'}</p>
                    <p className="mt-1 text-cyber-cyan">→ {item.latest || '未取得'}</p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="capitalize text-surface-300">{item.source || 'unbound'}</p>
                    <p className="mt-1 truncate text-[9px] text-surface-500">{item.source_key || '尚未绑定'}</p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className={label[1]}>{item.ui_status === 'syncing' ? '正在同步' : item.ui_status === 'synced' ? '同步完成' : item.ui_status === 'failed' ? '同步失败' : label[0]}</p>
                    <p className={`mt-1 text-[10px] ${item.ui_status === 'failed' ? 'text-cyber-red' : 'text-surface-500'}`}>
                      {item.ui_message || item.reason || ''}
                    </p>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-700 px-4 py-3">
        <div className="flex gap-2">
          <button type="button" disabled={running} onClick={() => setSelected(new Set(selectable.map(item => String(item.mod_id))))} className="btn-ghost px-2.5 py-1.5 text-[11px]">全选可同步</button>
          <button type="button" disabled={running} onClick={() => setSelected(new Set())} className="btn-ghost px-2.5 py-1.5 text-[11px]">清空</button>
        </div>
        <button type="button" disabled={running || !selected.size} onClick={syncSelected} className="btn-cyber px-4 py-2 text-xs disabled:opacity-40">
          {running ? '正在逐项同步…' : `同步更新 ${selected.size} 项`}
        </button>
      </footer>
    </section>
  )
}

export default function ChatPage({ status, games, onGameChange, onGameImport, onGamesRefresh, toast, api, onRefresh }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(() => sessionStorage.getItem('chat_draft') || '')
  const [loading, setLoading] = useState(false)
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(
    () => !window.matchMedia('(max-width: 1100px)').matches
  )
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [editingMsgId, setEditingMsgId] = useState(null)
  const [editDraft, setEditDraft] = useState('')
  const [expandedRaw, setExpandedRaw] = useState({})
  const toggleRaw = (id) => setExpandedRaw(prev => ({ ...prev, [id]: !prev[id] }))
  const [taskProgress, setTaskProgress] = useState(null)
  const [skeleton, setSkeleton] = useState(false)
  const [gameSearch, setGameSearch] = useState('')
  const [gameOpen, setGameOpen] = useState(false)
  const [gameImportOpen, setGameImportOpen] = useState(false)
  const [gameImportBusy, setGameImportBusy] = useState(false)
  const [gameScanBusy, setGameScanBusy] = useState(false)
  const [gameImportForm, setGameImportForm] = useState({
    game_name: '',
    game_root: '',
    executable: '',
    game_slug: '',
  })
  const [devOpen, setDevOpen] = useState(false)
  const bottomRef = useRef(null)
  const autoScrollSignatureRef = useRef('')
  const abortRef = useRef(null)
  const recoveryTimerRef = useRef(null)
  const recoveryCursorRef = useRef(0)
  const recoveryAgentRef = useRef({ id: null, text: '' })
  const idRef = useRef(0)
  const activeSessionRef = useRef(null)

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1100px)')
    const handleCompactChange = event => {
      // Entering compact mode releases the workspace width. The user can
      // still reopen the session list as a drawer with the existing button.
      if (event.matches) setSidebarOpen(false)
    }
    query.addEventListener('change', handleCompactChange)
    return () => query.removeEventListener('change', handleCompactChange)
  }, [])

  const mkId = () => `m${Date.now()}_${++idRef.current}`

  const rescanGames = async () => {
    if (gameScanBusy || !status.online) return
    setGameScanBusy(true)
    emitFeedback('scan-start', { source: 'game-library' })
    try {
      const before = new Set(
        games.map(game => String(game.path || '').replace(/\\/g, '/').toLowerCase())
      )
      const detected = await onGamesRefresh?.()
      const list = Array.isArray(detected) ? detected : []
      const added = list.filter(game => (
        !before.has(String(game.path || '').replace(/\\/g, '/').toLowerCase())
      ))
      setGameOpen(false)
      setGameSearch('')
      emitFeedback('scan-complete', { source: 'game-library', count: added.length })
      toast(
        added.length
          ? `游戏扫描完成：发现 ${added.length} 款新游戏，共 ${list.length} 款`
          : `游戏扫描完成：共 ${list.length} 款，未发现新增`
      )
    } catch (_) {
      emitFeedback('error', { source: 'game-library' })
      toast('重新扫描游戏失败，请检查本地服务后重试', 'error')
    } finally {
      setGameScanBusy(false)
    }
  }

  // 让流式回复只写入"发送时所属的会话"，切走后不串味
  useEffect(() => { activeSessionRef.current = activeSession }, [activeSession])

  useEffect(() => {
    const last = messages[messages.length - 1]
    const signature = [
      messages.length,
      last?.id || '',
      last?.role || '',
      last?.kind || '',
      String(last?.content || '').length,
    ].join(':')
    // Recommendation checkbox changes only mutate an existing message payload.
    // They must not steal the user's reading position by scrolling the whole
    // transcript to the bottom.
    if (signature === autoScrollSignatureRef.current) return
    autoScrollSignatureRef.current = signature
    // Streaming can add a long answer and a large decision table in quick
    // succession. Queuing smooth-scroll animations for both makes Chromium
    // spend seconds laying out the transcript and can look like a frozen UI.
    bottomRef.current?.scrollIntoView({ behavior: loading ? 'auto' : 'smooth' })
  }, [messages, loading])

  // Download callbacks carry real byte progress. While a chat task is active,
  // promote that signal into the main task bar instead of showing a synthetic
  // text/token counter.
  useEffect(() => {
    if (!loading) return undefined
    let cancelled = false
    const poll = async () => {
      try {
        const response = await fetch(`${api}/downloads/status`)
        if (!response.ok) return
        const download = await response.json()
        if (cancelled || !download?.active || !Array.isArray(download.items)) return
        const current = download.items.find(item => item.status === 'downloading')
        const currentLabel = current?.name
          ? `${current.name}${current.source_label ? `（${current.source_label}）` : ''}`
          : ''
        setTaskProgress(previous => ({
          ...(previous || {}),
          label: currentLabel ? `正在下载：${currentLabel}` : `正在下载 ${download.items.length} 个 Mod`,
          mode: 'determinate',
          pct: Number(download.overall_pct) || 0,
          etaSeconds: download.eta_seconds,
          expectedSeconds: null,
        }))
      } catch (_) {}
    }
    poll()
    const timer = setInterval(poll, 800)
    return () => { cancelled = true; clearInterval(timer) }
  }, [api, loading])

  useEffect(() => { loadSessions(); setActiveSession(null); setMessages([]) }, [status.game_slug, status.game_instance_id])

  const loadSessions = async () => {
    try {
      const scope = status.game_instance_id || status.game_slug || ''
      const url = scope ? `${api}/sessions?game_slug=${encodeURIComponent(scope)}` : `${api}/sessions`
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

  const persistEditionState = async (sid, payload) => {
    if (!sid || !payload) return
    try {
      await fetch(`${api}/sessions/${sid}/ui-state`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: payload }),
      })
    } catch (_) {}
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
      if (d.ui_state?.kind === 'recommendation_set'
          && Array.isArray(d.ui_state.items)
          && ['recommendation', 'confirm', 'executing'].includes(d.ui_state.phase || 'recommendation')) {
        const positioned = insertRecommendationAtAnchor(norm, d.ui_state, mkId)
        norm.splice(0, norm.length, ...positioned)
      }
      setMessages(norm)
      if (window.matchMedia?.('(max-width: 1280px)').matches) {
        setSidebarOpen(false)
      }
    } catch (_) { toast('加载会话失败', 'error') }
    setSkeleton(false)
  }

  const applyRecoveredEvents = (events, taskStartedAt) => {
    for (const data of events || []) {
      if (data.error) {
        recoveryAgentRef.current = { id: null, text: '' }
        setMessages(prev => [...prev, { id: mkId(), role: 'error', content: '[ERR] ' + data.error }])
        continue
      }
      if (data.tool) {
        recoveryAgentRef.current = { id: null, text: '' }
        const uniq = [...new Set(data.tool)]
        const visible = uniq.filter(name => !QUIET_TOOLS.has(name))
        if (visible.length) {
          setMessages(prev => [...prev, {
            id: mkId(), role: 'sys', kind: 'call',
            content: '正在执行：' + visible.map(name => TOOL_LABELS[name] || name).join('、'),
          }])
        }
        const now = Date.now()
        setTaskProgress(previous => ({
          ...(previous || { startedAt: taskStartedAt }),
          label: `正在${uniq.map(name => TOOL_LABELS[name] || name).join('、')}`,
          mode: 'indeterminate', pct: 0, etaSeconds: null,
          expectedSeconds: uniq.reduce((sum, name) => sum + (TOOL_STAGE_SECONDS[name] || 12), 0),
          stageStartedAt: now,
        }))
        continue
      }
      if (data.tool_result) {
        recoveryAgentRef.current = { id: null, text: '' }
        const tr = data.tool_result
        if (!QUIET_TOOLS.has(tr.name)) {
          setMessages(prev => [...prev, {
            id: mkId(), role: 'sys', kind: 'tool', ok: tr.ok, name: tr.name,
            summary: tr.summary || `${tr.ok ? '✅' : '❌'} ${tr.name}`,
            raw: tr.preview || '',
          }])
        }
        continue
      }
      if (data.recommendations?.kind === 'recommendation_set') {
        recoveryAgentRef.current = { id: null, text: '' }
        setMessages(prev => {
          const payload = {
            ...data.recommendations,
            phase: 'recommendation',
            anchor_after_text_count: textMessageCount(prev),
          }
          // Recovery can replay an already delivered SSE event, so suppress
          // only that exact card. An older recommendation card elsewhere in
          // the conversation must not hide the current search result.
          if (hasSameRecommendation(prev, payload)) return prev
          return insertRecommendationAtAnchor(prev, payload, mkId)
        })
        continue
      }
      if (data.recommendations_update?.kind === 'recommendation_set') {
        recoveryAgentRef.current = { id: null, text: '' }
        setMessages(prev => mergeRecommendationUpdate(
          prev, data.recommendations_update, mkId
        ))
        continue
      }
      if (Array.isArray(data.update_report?.items)) {
        recoveryAgentRef.current = { id: null, text: '' }
        setMessages(prev => [...prev, { id: mkId(), role: 'update-report', payload: data.update_report }])
        continue
      }
      if (data.chunk) {
        const current = recoveryAgentRef.current
        if (!current.id) {
          const id = mkId()
          recoveryAgentRef.current = { id, text: data.chunk }
          setMessages(prev => [...prev, { id, role: 'agent', content: data.chunk }])
        } else {
          current.text += data.chunk
          setMessages(prev => prev.map(message => message.id === current.id
            ? { ...message, content: current.text } : message))
        }
        setTaskProgress(previous => previous ? {
          ...previous, label: '正在整理结果', mode: 'indeterminate',
          expectedSeconds: 6, stageStartedAt: Date.now(),
        } : previous)
      }
    }
  }

  useEffect(() => {
    let cancelled = false
    const recover = async () => {
      let taskFinished = false
      try {
        const scope = status.game_instance_id || status.game_slug || ''
        const response = await fetch(`${api}/chat/tasks/active?game_slug=${encodeURIComponent(scope)}`)
        const active = await response.json()
        if (cancelled || !active?.active || !active.session_id) return
        await selectSession({ id: active.session_id })
        if (cancelled) return
        const startedAt = Number(active.started || 0) * 1000 || Date.now()
        setLoading(true)
        setProgressClock(Date.now())
        setTaskProgress({
          label: '已重新连接，正在恢复任务进度', mode: 'indeterminate', pct: 0,
          startedAt, stageStartedAt: Date.now(), etaSeconds: null, expectedSeconds: 12,
        })
        recoveryCursorRef.current = 0
        recoveryAgentRef.current = { id: null, text: '' }

        const poll = async () => {
          try {
            const result = await fetch(
              `${api}/chat/tasks/${encodeURIComponent(active.session_id)}?after=${recoveryCursorRef.current}`
            ).then(value => value.json())
            if (cancelled) return
            applyRecoveredEvents(result.events, startedAt)
            recoveryCursorRef.current = Number(result.cursor) || recoveryCursorRef.current
            if (result.done) {
              taskFinished = true
              clearInterval(recoveryTimerRef.current)
              recoveryTimerRef.current = null
              setLoading(false)
              setTaskProgress(null)
              await selectSession({ id: active.session_id })
              loadSessions()
            }
          } catch (_) {}
        }
        await poll()
        if (!cancelled && !taskFinished && recoveryTimerRef.current == null) {
          recoveryTimerRef.current = setInterval(poll, 650)
        }
      } catch (_) {}
    }
    recover()
    return () => {
      cancelled = true
      if (recoveryTimerRef.current) clearInterval(recoveryTimerRef.current)
      recoveryTimerRef.current = null
    }
  }, [api, status.game_slug, status.game_instance_id])

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
    emitFeedback('notice', { source: 'clipboard' })
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
    // 把本轮已生效的副作用告诉后端。重新生成只改回答，后端会移除所有
    // 写文件/下载/安装/快照/网页操作工具，不再重放，也不再二次询问。
    const effects = []
    for (let k = uIdx + 1; k <= idx; k++) {
      const m = messages[k]
      if (m.role === 'sys' && m.kind === 'tool' && m.name && SIDE_EFFECT_TOOLS.has(m.name)) {
        effects.push(m.summary || m.name)
      }
    }
    sendMsg(userText, base, { regenerate: true, completedEffects: effects })
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
    emitFeedback('cancel', { source: 'chat-undo' })
    toast('已撤回')
  }

  const stopStream = async () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
      setTaskProgress(null)
      emitFeedback('cancel', { source: 'chat-stop' })
      try {
        const response = await fetch(`${api}/tasks/cancel`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: activeSessionRef.current || '' }),
        })
        const result = await response.json()
        toast(
          result?.ok
            ? '已停止；旧任务不会继续执行'
            : '界面已停止，但后端未找到匹配任务',
          result?.ok ? 'success' : 'warn',
        )
      } catch (_) {
        toast('界面已停止；后台取消请求发送失败', 'error')
      }
    }
  }

  const updateEditionSelection = (message, selectedKeys, wantedKeys = message.payload.wanted_keys || []) => {
    const payload = {
      ...message.payload,
      selected_keys: selectedKeys,
      wanted_keys: wantedKeys,
    }
    setMessages(prev => prev.map(item => item.id === message.id ? { ...item, payload } : item))
    persistEditionState(activeSession, payload)
  }

  const resolveEditionItem = async (message, item, action) => {
    const wantedKeys = [...new Set([
      ...(message.payload.wanted_keys || []),
      item.selection_key,
    ])]
    updateEditionSelection(
      message,
      message.payload.selected_keys || [],
      wantedKeys,
    )
    if (action === 'open_source') {
      if (!item.url) {
        toast('该候选尚无可打开的稳定来源页', 'warn')
        return
      }
      const result = await window.modagent?.openExternal?.(item.url)
      if (!result?.ok) toast(result?.error || '无法打开来源页', 'error')
      return
    }
    const identity = [
      item.source_label || item.source,
      item.source_id || item.mod_id || '',
    ].filter(Boolean).join(' ')
    if (action === 'verify_detail') {
      sendMsg(
        `我仍然想要 ${item.name}${identity ? `（${identity}）` : ''}。请重新核验它的详情、可下载文件、前置依赖和适配风险；不要猜测同名项目，核验后告诉我怎样继续安装。`
      )
      return
    }
    if (action === 'manual_import') {
      if (item.url) await window.modagent?.openExternal?.(item.url)
      sendMsg(
        `我仍然想要 ${item.name}${identity ? `（${identity}）` : ''}。如果站点不能自动下载，请保留这个目标，并指导我下载后通过本地安装包导入；导入前仍要核验文件身份、必要依赖和安装落点。`
      )
    }
  }

  const resolveWantedItems = (message, items) => {
    if (loading || !items?.length) return
    const names = items.map(item => item.name).filter(Boolean)
    sendMsg(
      `请批量补齐我在当前智能推荐决策表中标记“我要这个”的 ${items.length} 个明确目标：${names.join('、')}。逐项核验权威详情、可下载文件、当前游戏版本适配、已安装状态、冲突和完整必要依赖；把兼容且缺少的必要依赖加入本轮拟安装计划，然后用“本机已安装 + 本轮拟安装依赖”重新检测并刷新原智能推荐决策表。共享依赖只解除其他候选的同类阻塞，不要自动选择未标记的 Mod，也不要在最终确认前下载或安装。`,
      undefined,
      {
        recommendationSelection: items,
        selectionAction: 'resolve',
      },
    )
  }

  const submitEditionSelection = (message, selectedItems) => {
    if (loading || !selectedItems.length) return
    const count = selectedItems.length
    if (message.payload.phase === 'confirm') {
      const executingPayload = {
        ...message.payload,
        phase: 'executing',
        selected_keys: selectedItems.map(item => item.selection_key),
      }
      setMessages(prev => prev.map(item => item.id === message.id
        ? { ...item, payload: executingPayload } : item))
      persistEditionState(activeSession, executingPayload)
      sendMsg(`确认安装表中最终勾选的 ${count} 个 Mod。`, undefined, {
        recommendationSelection: selectedItems,
        selectionAction: 'confirm',
        editionCompletion: {
          messageId: message.id,
          completed: { ...executingPayload, phase: 'completed' },
          failed: { ...executingPayload, phase: 'confirm' },
        },
      })
      return
    }
    const confirmationPayload = {
      ...message.payload,
      phase: 'confirm',
      selected_keys: selectedItems.map(item => item.selection_key),
    }
    sendMsg(`请为我在推荐决策表中勾选的 ${count} 个 Mod 生成安装计划。`, undefined, {
      recommendationSelection: selectedItems,
      selectionAction: 'plan',
      confirmationPayload,
    })
  }

  const sendMsg = async (overrideText, baseMessages, options = {}) => {
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
        emitFeedback('error', { source: 'chat-history-sync' })
        toast('无法截断旧回复，重新生成已取消', 'error')
        return
      }
    }

    const userMsg = { id: mkId(), role: 'user', content: text }
    setMessages(prev => [...(baseMessages || prev), userMsg])
    setLoading(true)
    const taskStartedAt = Date.now()
    setTaskProgress({
      label: '正在理解请求并规划步骤', mode: 'indeterminate', pct: 0,
      startedAt: taskStartedAt, stageStartedAt: taskStartedAt,
      etaSeconds: null, expectedSeconds: null,
    })

    const controller = new AbortController()
    abortRef.current = controller

    const sendSid = sid
    // 仅当用户仍停留在发送时的会话才更新界面（否则后端照常保存，切回时从 DB 重载）
    const guardedSet = (updater) => { if (activeSessionRef.current === sendSid) setMessages(updater) }

    let curAgentId = null   // 当前正在流式的 agent 消息 id
    let segText = ''        // 当前段落累计文本
    let transcriptTextCount = textMessageCount(baseMessages || messages) + 1
    let streamCompleted = false
    let streamFailed = false
    let executionFailed = false
    let planBlocked = false
    let latestRecommendationUpdate = null

    try {
      const r = await fetch(api + '/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sid,
          regenerate: !!options.regenerate,
          completed_effects: options.completedEffects || [],
          recommendation_selection: options.recommendationSelection || [],
          selection_action: options.selectionAction || '',
        }),
        signal: controller.signal,
      })

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      let sawDoneEvent = false
      while (!sawDoneEvent) {
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
              streamFailed = true
              emitFeedback('error', { source: 'chat-stream' })
              guardedSet(prev => [...prev, { id: mkId(), role: 'error', content: '[ERR] ' + data.error }])
              continue
            }
            if (data.tool) {
              curAgentId = null
              const uniq = [...new Set(data.tool)]
              const stageStartedAt = Date.now()
              const expectedSeconds = uniq.reduce((sum, name) => sum + (TOOL_STAGE_SECONDS[name] || 12), 0)
              const stageNames = uniq.map(name => TOOL_LABELS[name] || name)
              setTaskProgress(previous => ({
                ...(previous || { startedAt: taskStartedAt }),
                label: `正在${stageNames.join('、')}`,
                mode: 'indeterminate', pct: 0, etaSeconds: null,
                expectedSeconds, stageStartedAt,
              }))
              uniq.forEach(name => emitToolStartFeedback(name, { source: 'chat-tool' }))
              const visible = uniq.filter(name => !QUIET_TOOLS.has(name))
              if (visible.length) {
                guardedSet(prev => [...prev, { id: mkId(), role: 'sys', kind: 'call', content: '正在执行：' + visible.map(name => TOOL_LABELS[name] || name).join('、') }])
              }
              continue
            }
            if (data.tool_result) {
              curAgentId = null
              const tr = data.tool_result
              if (
                options.selectionAction === 'confirm'
                && ['mod_download', 'batch_download', 'mod_install', 'mod_install_batch', 'mod_install_custom'].includes(tr.name)
                && !tr.ok
              ) {
                executionFailed = true
              }
              if (QUIET_TOOLS.has(tr.name)) continue
              setTaskProgress(previous => ({
                ...(previous || { startedAt: taskStartedAt }),
                label: `${TOOL_LABELS[tr.name] || tr.name}已完成，正在继续处理`,
                mode: 'indeterminate', pct: 0, etaSeconds: null,
                expectedSeconds: null, stageStartedAt: Date.now(),
              }))
              emitToolFeedback(tr.name, tr.ok, { preview: tr.preview || '' })
              guardedSet(prev => [...prev, {
                id: mkId(), role: 'sys', kind: 'tool',
                ok: tr.ok, name: tr.name,
                summary: tr.summary || `${tr.ok ? '✅' : '❌'} ${tr.name}`,
                raw: tr.preview || '',
              }])
              continue
            }
            if (data.recommendations?.kind === 'recommendation_set') {
              curAgentId = null
              const payload = {
                ...data.recommendations,
                phase: 'recommendation',
                anchor_after_text_count: transcriptTextCount,
              }
              guardedSet(prev => [...prev, { id: mkId(), role: 'edition', payload }])
              persistEditionState(sendSid, payload)
              continue
            }
            if (data.plan_blocked) {
              planBlocked = true
              continue
            }
            if (data.recommendations_update?.kind === 'recommendation_set') {
              curAgentId = null
              latestRecommendationUpdate = data.recommendations_update
              planBlocked = planBlocked || !!data.plan_blocked
              guardedSet(prev => mergeRecommendationUpdate(
                prev, data.recommendations_update, mkId
              ))
              persistEditionState(sendSid, data.recommendations_update)
              continue
            }
            if (Array.isArray(data.update_report?.items)) {
              curAgentId = null
              guardedSet(prev => [...prev, {
                id: mkId(), role: 'update-report', payload: data.update_report,
              }])
              continue
            }
            if (data.done) {
              // "done" is the protocol boundary. Release interactive controls
              // immediately instead of waiting for the HTTP body to close.
              // Some proxies/antivirus products keep the body open briefly.
              sawDoneEvent = true
              streamCompleted = true
              setLoading(false)
              setTaskProgress(null)
              break
            }
            if (data.chunk) {
              setTaskProgress(previous => {
                if (!previous || previous.label === '正在整理结果') return previous
                return {
                  ...previous, label: '正在整理结果', mode: 'indeterminate',
                  pct: 0, etaSeconds: null, expectedSeconds: 6,
                  stageStartedAt: Date.now(),
                }
              })
              if (curAgentId === null) {
                const id = mkId()
                curAgentId = id
                segText = data.chunk
                transcriptTextCount += 1
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
        if (sawDoneEvent) {
          try { await reader.cancel() } catch (_) {}
          break
        }
      }

      streamCompleted = true
      loadSessions()
    } catch (e) {
      if (e.name === 'AbortError') {
        if (options.editionCompletion) {
          const completion = options.editionCompletion
          guardedSet(prev => prev.map(item => item.id === completion.messageId
            ? { ...item, payload: completion.failed } : item))
          persistEditionState(sendSid, completion.failed)
        }
        setLoading(false)
        setTaskProgress(null)
        abortRef.current = null
        return
      }
      streamFailed = true
      setMessages(prev => [...prev, { id: mkId(), role: 'error', content: '连接失败: ' + e.message }])
    }

    if (streamCompleted && options.confirmationPayload && !planBlocked) {
      const payload = {
        ...(latestRecommendationUpdate || options.confirmationPayload),
        phase: 'confirm',
      }
      guardedSet(prev => [...prev, { id: mkId(), role: 'edition', payload }])
      // A completed card already had its chronological position in the live
      // transcript. Do not persist it as floating UI state: on reload that
      // state would be appended after every later message and look like a new,
      // unsolicited installation request.
      persistEditionState(sendSid, payload.phase === 'completed' ? {} : payload)
    }
    if (streamCompleted && options.confirmationPayload && planBlocked) {
      toast('该候选未通过依赖或加载器核验，已保留为目标但不会进入安装确认', 'warn')
    }
    if (options.editionCompletion) {
      const completion = options.editionCompletion
      const payload = streamCompleted && !streamFailed && !executionFailed
        ? completion.completed : completion.failed
      guardedSet(prev => prev.map(item => item.id === completion.messageId
        ? { ...item, payload } : item))
      persistEditionState(sendSid, payload)
    }
    if (streamCompleted && !streamFailed) {
      let replySoundEnabled = true
      let windowsNotificationEnabled = false
      try {
        replySoundEnabled = localStorage.getItem('modagent-reply-sound-enabled') !== 'false'
        windowsNotificationEnabled = localStorage.getItem('modagent-reply-windows-notification') === 'true'
      } catch (_) {}
      if (replySoundEnabled) emitFeedback('reply-complete', { source: 'chat-complete' })
      if (windowsNotificationEnabled && (document.hidden || !document.hasFocus())) {
        window.modagent?.notifyReplyComplete?.()
      }
    }
    setLoading(false)
    setTaskProgress(null)
    abortRef.current = null
  }

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg() } }

  const renderMessage = (msg, i) => {
    if (msg.role === 'update-report') {
      return (
        <div key={msg.id} className="animate-fade-in w-full py-1">
          <UpdateReportCard payload={msg.payload} api={api} toast={toast} onRefresh={onRefresh} />
        </div>
      )
    }
    if (msg.role === 'edition') {
      return (
        <div key={msg.id} className="animate-fade-in w-full py-1">
          <ChatEditionMessage
            message={msg}
            disabled={loading}
            onChange={(selectedKeys, wantedKeys) => updateEditionSelection(msg, selectedKeys, wantedKeys)}
            onSubmit={selectedItems => submitEditionSelection(msg, selectedItems)}
            onResolve={(item, action) => resolveEditionItem(msg, item, action)}
            onResolveWanted={items => resolveWantedItems(msg, items)}
          />
        </div>
      )
    }
    const isAgent = msg.role === 'agent'
    const isUser = msg.role === 'user'
    const isError = msg.role === 'error'
    const isSys = msg.role === 'sys'
    const isLast = i === messages.length - 1
    const editing = editingMsgId === msg.id
    const manualActionReply = (
      isAgent && isLast && !editing
        ? getManualActionQuickReply(msg.content)
        : null
    )

    return (
      <div key={msg.id} className="group relative">
        <div
          className={`chat-message ${isUser ? 'chat-message-user' : isAgent ? 'chat-message-agent' : ''} animate-fade-in max-w-[85%] px-3.5 py-2.5 rounded-lg text-sm leading-relaxed whitespace-pre-wrap break-words relative
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

          {manualActionReply && !(loading && isLast) && (
            <div className="mt-3 pt-3 border-t border-cyber-cyan/20">
              <button
                type="button"
                onClick={() => sendMsg(manualActionReply.message)}
                disabled={loading || !status.online}
                title="完成页面验证后，继续刚才被中断的同一任务"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md border border-cyber-cyan/50 bg-cyber-cyan/15 text-cyber-cyan font-medium hover:bg-cyber-cyan/25 hover:border-cyber-cyan disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Check size={15} />
                {manualActionReply.label}
              </button>
            </div>
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
    (status.game_instance_id && g.game_instance_id === status.game_instance_id) ||
    (status.game_root && _normPath(g.path) === _normPath(status.game_root))
  ) || null
  const gameSourceLabel = source => ({
    steam_acf: 'Steam',
    epic_manifest: 'Epic',
    ea_registry: 'EA',
    ea_library: 'EA',
    gog_registry: 'GOG',
    gog_library: 'GOG',
    wegame_rail: 'WeGame',
    xbox_gaming_root: 'Xbox',
    manual: '手动',
  })[source] || ''

  const openGameImport = () => {
    setGameOpen(false)
    setGameSearch('')
    setGameImportOpen(true)
  }

  const applyGameSelection = (selected) => {
    if (!selected) return
    setGameImportForm(prev => ({
      ...prev,
      game_root: selected.path || prev.game_root,
      executable: selected.executable || '',
      game_name: prev.game_name || selected.suggestedName || '',
    }))
  }

  const monitorInventoryScan = async (gameInstanceId, label) => {
    if (!gameInstanceId) return
    for (let attempt = 0; attempt < 180; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      try {
        const response = await fetch(
          `${api}/mods/scan-status?game_instance_id=${encodeURIComponent(gameInstanceId)}`
        )
        if (!response.ok) continue
        const state = await response.json()
        if (state.status === 'completed') {
          const imported = Number(state.imported || 0)
          const detected = Number(state.detected || 0)
          toast(
            imported > 0
              ? `${label}扫描完成：已导入 ${imported} 个 Mod`
              : `${label}扫描完成：发现 ${detected} 项，清单无需新增`
          )
          onRefresh?.()
          return
        }
        if (state.status === 'failed') {
          toast(state.error || `${label}扫描失败`, 'error')
          return
        }
      } catch (_) {
        // The backend may be restarting; the next poll can still recover.
      }
    }
    toast(`${label}目录较大，仍在后台扫描；你可以继续使用其他功能`)
  }

  const submitGameImport = async () => {
    if (!gameImportForm.game_name.trim() || !gameImportForm.game_root.trim()) {
      toast('请填写游戏名称并选择游戏目录或主程序', 'error')
      return
    }
    setGameImportBusy(true)
    try {
      const result = await onGameImport({
        ...gameImportForm,
        game_name: gameImportForm.game_name.trim(),
        game_root: gameImportForm.game_root.trim(),
        game_slug: gameImportForm.game_slug.trim(),
      })
      setGameImportOpen(false)
      setGameImportForm({ game_name: '', game_root: '', executable: '', game_slug: '' })
      const scan = result.mod_scan || {}
      const scanCount = Number(scan.identified_count ?? scan.imported ?? (scan.identified || []).length)
      if (scan.queued) {
        toast(`已导入 ${result.game?.name || gameImportForm.game_name}；正在后台扫描 Mod`)
        void monitorInventoryScan(result.game?.game_instance_id, '游戏 Mod')
      } else if (scan.error) {
        toast(scan.error, 'error')
      } else {
        toast(`已导入并扫描 ${result.game?.name || gameImportForm.game_name}：发现 ${scanCount} 个已有 Mod`)
      }
    } catch (error) {
      toast(error.message || '游戏导入失败', 'error')
    } finally {
      setGameImportBusy(false)
    }
  }

  const importModDirectory = async () => {
    const selected = await window.modagent?.selectModDirectory?.()
    if (!selected?.path) return
    emitFeedback('scan-start', { source: 'manual-mod-directory' })
    try {
      const response = await fetch(api + '/mods/import-directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: selected.path }),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(result.detail || result.error || 'Mod 目录导入失败')
      const imported = Number(result.imported || 0)
      const detected = Number(result.detected || 0)
      if (result.queued) {
        toast('Mod 目录已保存；正在后台扫描，大型目录不会阻塞界面')
        void monitorInventoryScan(status.game_instance_id || status.game_slug, '外部 Mod')
      } else if (imported > 0) toast(`已保存目录并导入 ${imported} 个 Mod`)
      else if (detected > 0) toast(`目录已保存；发现 ${detected} 项，均已在清单中`)
      else toast('目录已保存，但未发现受支持的 Mod 文件', 'error')
      emitFeedback('scan-complete', { count: imported })
      onRefresh?.()
    } catch (error) {
      emitFeedback('error', { source: 'manual-mod-directory' })
      toast(error.message || 'Mod 目录导入失败', 'error')
    }
  }

  return (
    <div className={`chat-layout flex flex-1 h-full min-h-0 min-w-0 overflow-hidden ${
      sidebarOpen ? 'has-session-rail' : 'without-session-rail'
    }`}>
      {sidebarOpen && (
        <div className="chat-session-rail w-56 min-w-[224px] h-full min-h-0 overflow-hidden bg-surface-800 border-r border-surface-600 flex flex-col">
          <div className="chat-session-header shrink-0 flex items-center gap-2 p-3 border-b border-surface-600">
            <button onClick={newSession} className="btn-cyber min-w-0 flex-1 flex items-center justify-center gap-2">
              <Plus size={14} /> 新对话
            </button>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="chat-session-close btn-ghost shrink-0 p-2"
              title="关闭会话列表"
              aria-label="关闭会话列表"
            >
              <PanelLeftClose size={16} />
            </button>
          </div>
          <div className="chat-session-list flex-1 min-h-0 overflow-y-auto p-2 space-y-3">
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

      <div className="chat-primary-pane flex-[7] h-full min-h-0 overflow-hidden flex flex-col min-w-0">
        <div className="chat-primary-toolbar shrink-0 relative z-30 flex items-center gap-3 px-3 py-2 border-b border-surface-600 bg-surface-800">
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
                    <span className="truncate">{g.name}</span>
                    <span className="shrink-0 flex items-center gap-1">
                      {gameSourceLabel(g.source) && <span className="text-[10px] text-surface-500">{gameSourceLabel(g.source)}</span>}
                      {!g.adapted && <span className="text-[10px] text-amber-400/80">开放</span>}
                    </span>
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
                    {!stable.length && !open.length && (
                      <div className="px-3 py-3 text-xs text-surface-500">没有匹配的已安装游戏</div>
                    )}
                    <button
                      className="w-full px-2 py-2 border-t border-surface-600 text-xs text-cyber-cyan hover:bg-surface-600 flex items-center gap-2"
                      onClick={openGameImport}
                    >
                      <FolderPlus size={13} /> 手动导入游戏…
                    </button>
                  </div>
                )
              })()}
              {/* Click outside to close */}
              {gameOpen && <div className="fixed inset-0 z-40" onClick={() => { setGameOpen(false); setGameSearch('') }} />}
            </div>
            <button
              type="button"
              disabled={!status.online || gameScanBusy}
              onClick={rescanGames}
              className="tc-icon-button shrink-0 rounded border border-surface-600 p-1.5 text-surface-400 hover:border-cyber-cyan/40 hover:text-cyber-cyan disabled:cursor-wait disabled:opacity-45"
              title="重新扫描 Steam、Epic、EA、GOG、WeGame、Xbox 和手动导入的游戏"
              aria-label="重新扫描游戏"
            >
              <RefreshCw size={13} className={gameScanBusy ? 'animate-spin' : ''} />
            </button>
            {currentGame && !currentGame.adapted && (
              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-amber-400/10 text-amber-400 border border-amber-400/30"
                title="该游戏未特化适配:搜索/安装走通用兜底规则,落位不保证;快照走目录嗅探。结果请自行核对。">
                开放模式
              </span>
            )}
            <span className="text-[11px] text-surface-500 truncate flex-1">{status.game_root}</span>
          </div>
        <div className="chat-message-scroll flex-1 min-h-0 overflow-y-auto p-4 space-y-6">
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
          {loading && <ActiveTaskProgress task={taskProgress} />}
          <div ref={bottomRef} />
        </div>

        <div className="chat-composer shrink-0 p-3 border-t border-surface-600 bg-surface-800 flex items-end gap-2">
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
              <button onClick={() => sendMsg()} disabled={!input.trim() || !status.online}
              className="tc-icon-button p-2.5 rounded-md bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all">
              <Send size={16} />
            </button>
            </>
          )}
        </div>
      </div>

      <div className="chat-quick-sidebar flex-[3] h-full min-h-0 overflow-x-hidden overflow-y-auto border-l border-surface-600 bg-surface-800 p-4 flex flex-col gap-4 min-w-[220px]">
        <h3 className="text-xs font-semibold text-surface-500 uppercase tracking-wider">状态</h3>
        <div className="card-cyber"><div className="flex items-center justify-between"><span className="text-xs text-surface-500">已管理 Mod 包</span><span className="text-xl font-bold text-cyber-cyan">{status.mods == null ? '…' : status.mods}</span></div></div>
        <div className="card-cyber"><div className="flex items-center justify-between"><span className="text-xs text-surface-500">快照数量</span><span className="text-xl font-bold text-cyber-purple">{status.snaps == null ? '…' : status.snaps}</span></div></div>
        <div className="card-cyber">
          <span className="text-xs text-surface-500 block mb-1">游戏</span>
          <select
            className="w-full px-2 py-1 rounded text-xs bg-surface-700 border border-surface-500 text-white outline-none cursor-pointer"
            value={currentGame?.path || ''}
            disabled={!status.online || games.length === 0}
            onChange={e => {
              const g = games.find(x => x.path === e.target.value)
              if (g) onGameChange(g)
            }}
          >
            {/* currentGame 为空 = 后端配置的游戏不在检测列表里(已卸载/移动),兜底一个 value='' 的
                option,免得 select 匹配不到时静默跳到第一个游戏、误导用户以为切换了。 */}
            {!currentGame && <option value="">{!status.online ? '正在连接后端…' : gameScanBusy ? '正在检测游戏…' : games.length === 0 ? '未检测到游戏，可手动导入' : status.game ? `${status.game}(未在检测列表)` : '选择游戏...'}</option>}
            <optgroup label="稳定适配">
              {games.filter(g => g.adapted).map(g => (
                <option key={g.path} value={g.path}>{g.name}{gameSourceLabel(g.source) ? ` · ${gameSourceLabel(g.source)}` : ''}</option>
              ))}
            </optgroup>
            <optgroup label="开放模式(实验)">
              {games.filter(g => !g.adapted).map(g => (
                <option key={g.path} value={g.path}>{g.name}{gameSourceLabel(g.source) ? ` · ${gameSourceLabel(g.source)}` : ''}</option>
              ))}
            </optgroup>
          </select>
          <button
            type="button"
            onClick={rescanGames}
            disabled={!status.online || gameScanBusy}
            className="mt-2 w-full px-2 py-1.5 rounded text-xs border border-surface-500 text-surface-300 hover:border-cyber-cyan/40 hover:text-cyber-cyan disabled:cursor-wait disabled:opacity-40 flex items-center justify-center gap-1.5"
            title="无需重启 ModAgent，重新读取所有受支持游戏平台的已安装游戏"
          >
            <RefreshCw size={13} className={gameScanBusy ? 'animate-spin' : ''} />
            {gameScanBusy ? '正在扫描游戏…' : '重新扫描游戏'}
          </button>
          <button
            onClick={openGameImport}
            className="mt-2 w-full px-2 py-1.5 rounded text-xs border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 flex items-center justify-center gap-1.5"
          >
            <FolderPlus size={13} /> 手动导入游戏
          </button>
          <button
            onClick={importModDirectory}
            disabled={!status.online || !(status.game_instance_id || status.game_slug)}
            className="mt-2 w-full px-2 py-1.5 rounded text-xs border border-cyber-purple/30 text-cyber-purple hover:bg-cyber-purple/10 disabled:opacity-40 flex items-center justify-center gap-1.5"
            title="选择 Vortex 暂存、MO2 mods、Fluffy 或其他外部 Mod 目录；保存后每次扫描都会自动包含"
          >
            <FolderOpen size={13} /> 添加 Mod 目录
          </button>
        </div>
        <div className="h-px bg-surface-600" />
        <h3 className="text-xs font-semibold text-surface-500 uppercase tracking-wider">快捷操作</h3>
        <button
          disabled={!status.online || loading}
          className="btn-cyber flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-wait"
          onClick={() => sendMsg('请自动对齐当前游戏已安装 Mod 的维护来源，检查所有可用更新，并给出绑定成功、未绑定、版本未知和检查失败的可交互报告。')}
        ><RefreshCw size={14}/> 检查更新</button>
        <button disabled={!status.online} className="btn-cyber flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-wait" onClick={async () => {
          emitFeedback('scan-start', { source: 'quick-action' })
          try {
            const r = await fetch(api + '/tool/scan_existing_mods', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
            const d = await r.json()
            const data = JSON.parse(d.result || '{}')
            if (data.error) {
              emitFeedback('error', { source: 'scan' })
              toast('扫描失败', 'error')
              return
            }
            const identified = data.identified || []
            if (identified.length > 0) {
              toast(`已导入 ${identified.length} 个 Mod`)
              onRefresh?.()
            } else {
              toast('未检测到新 Mod')
            }
            emitFeedback('scan-complete', { count: identified.length })
          } catch (e) { emitFeedback('error', { source: 'scan' }); toast('扫描失败', 'error') }
        }}><Search size={14}/> 扫描已有 Mod</button>
        <button disabled={!status.online} className="btn-cyber flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-wait" onClick={async () => {
          try {
            const r = await fetch(api + '/tool/snapshot_create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trigger_mod_name: '手动快照' }) })
            const d = await r.json()
            const data = JSON.parse(d.result || '{}')
            if (data.error) { emitFeedback('error', { source: 'snapshot' }); toast(data.error.length > 80 ? '快照创建失败' : data.error, 'error') }
            else { emitFeedback('snapshot-complete', { snapshotId: data.snapshot_id }); toast('快照已创建: ' + (data.snapshot_id || '')); onRefresh?.() }
          } catch (e) { emitFeedback('error', { source: 'snapshot' }); toast('快照失败', 'error') }
        }}><Shield size={14}/> 创建快照</button>
      </div>
      <DebugPanel api={api} open={devOpen} onClose={() => setDevOpen(false)} />

      {gameImportOpen && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[70]" onClick={() => !gameImportBusy && setGameImportOpen(false)}>
          <div className="bg-surface-800 border border-cyber-cyan/30 rounded-lg p-5 w-[520px] max-w-[90vw] shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <FolderPlus size={15} className="text-cyber-cyan" /> 手动导入游戏
                </h3>
                <p className="text-xs text-surface-500 mt-1">适用于 EA、WeGame、自定义安装目录和没有启动器的游戏。</p>
              </div>
              <button disabled={gameImportBusy} onClick={() => setGameImportOpen(false)} className="text-surface-500 hover:text-white"><X size={16} /></button>
            </div>

            <label className="text-xs text-surface-400 block mb-1">游戏名称</label>
            <input
              className="input-cyber w-full mb-3"
              value={gameImportForm.game_name}
              onChange={event => setGameImportForm(prev => ({ ...prev, game_name: event.target.value }))}
              placeholder="例如：Need for Speed Unbound"
            />

            <label className="text-xs text-surface-400 block mb-1">游戏目录</label>
            <div className="flex gap-2 mb-2">
              <input className="input-cyber flex-1 min-w-0" readOnly value={gameImportForm.game_root} placeholder="尚未选择" />
              <button
                className="btn-ghost flex items-center gap-1.5 shrink-0"
                onClick={async () => applyGameSelection(await window.modagent?.selectGameDirectory?.())}
              >
                <FolderOpen size={14} /> 选目录
              </button>
            </div>
            <button
              className="w-full px-3 py-2 rounded border border-surface-600 text-xs text-surface-300 hover:border-cyber-cyan/40 hover:text-cyber-cyan flex items-center justify-center gap-2 mb-3"
              onClick={async () => applyGameSelection(await window.modagent?.selectGameExecutable?.())}
            >
              <FileType2 size={14} /> 或直接选择游戏主 EXE（特殊游戏推荐）
            </button>

            {gameImportForm.executable && (
              <div className="text-[11px] text-emerald-400/80 bg-emerald-400/5 border border-emerald-400/20 rounded px-2 py-1.5 mb-3 truncate">
                已确认主程序：{gameImportForm.executable}
              </div>
            )}

            <label className="text-xs text-surface-400 block mb-1">Nexus 游戏标识（可选）</label>
            <input
              className="input-cyber w-full"
              value={gameImportForm.game_slug}
              onChange={event => setGameImportForm(prev => ({ ...prev, game_slug: event.target.value }))}
              placeholder="不确定可以留空，ModAgent 会自动匹配"
            />
            <p className="text-[11px] text-surface-500 mt-2">选目录会继续执行结构检测；直接选 EXE 则视为用户已确认该游戏，适合小型 Unity 游戏或特殊启动结构。</p>

            <div className="flex justify-end gap-2 mt-5">
              <button disabled={gameImportBusy} onClick={() => setGameImportOpen(false)} className="btn-ghost">取消</button>
              <button disabled={gameImportBusy || !gameImportForm.game_name.trim() || !gameImportForm.game_root}
                onClick={submitGameImport}
                className="px-4 py-2 rounded-md text-sm bg-cyber-cyan/80 text-black font-medium hover:bg-cyber-cyan disabled:opacity-40">
                {gameImportBusy ? '正在导入…' : '导入并切换'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
