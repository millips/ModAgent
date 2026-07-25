import React, { useState, useEffect, useRef } from 'react'
import Sidebar from './components/Sidebar'
import ChatPage from './components/ChatPage'
import ModsPage from './components/ModsPage'
import SnapshotsPage from './components/SnapshotsPage'
import SettingsPage from './components/SettingsPage'
import SetupPage from './components/SetupPage'
import Toast from './components/Toast'
import DownloadPanel from './components/DownloadPanel'
import { emitFeedback } from './feedback/feedbackBus'
import { applyEditionDefaultBackground } from '@edition'

const exposedApiBase = window.modagent?.getApiBase?.()
const API = typeof exposedApiBase === 'string' ? exposedApiBase : 'http://127.0.0.1:18890'

export default function App() {
  const [page, setPage] = useState('chat')
  const [status, setStatus] = useState({ online: false, game: '', mods: null, snaps: null, game_root: '', game_slug: '', game_instance_id: '', bg: null })
  const [games, setGames] = useState([])
  const [configured, setConfigured] = useState(null)
  const [toasts, setToasts] = useState([])
  const nextToastId = useRef(0)
  const gameChangeSeq = useRef(0)
  const updateRef = useState(0)[1]

  const refreshCounts = () => updateRef(x => x + 1)
  const refreshGames = async () => {
    const response = await fetch(API + '/games/detect')
    if (!response.ok) throw new Error(`games detect ${response.status}`)
    const detected = await response.json()
    const list = Array.isArray(detected) ? detected : []
    setGames(list)
    return list
  }

  useEffect(() => {
    let cancelled = false
    let timer = null
    const check = async () => {
      try {
        const r = await fetch(API + '/health')
        if (r.ok) {
          const s = await fetch(API + '/status').then(r => r.json()).catch(() => ({}))
          setStatus(prev => ({
            ...prev,
            online: true,
            game: s.game_name || '',
            game_root: s.game_root || '',
            game_slug: s.game_slug || '',
            game_instance_id: s.game_instance_id || '',
            bg: s.bg || null,
          }))
          if (s.bg) document.body.classList.add('has-bg')
          setConfigured(s.api_key_set && s.tavily_set && s.llm_set)
          if (!window.__gamesDetected) {
            window.__gamesDetected = true
            refreshGames().catch(() => { window.__gamesDetected = false })
          }
          return true
        }
      } catch (_) {}
      setStatus(prev => ({ ...prev, online: false }))
      return false
    }
    const poll = async () => {
      const ready = await check()
      if (!cancelled) timer = setTimeout(poll, ready ? 15000 : 500)
    }
    poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  const [refreshToggle, setRefreshToggle] = useState(0)
  const [refreshKey, setRefreshKey] = useState(0)
  const doRefresh = () => { setRefreshToggle(x => x + 1); setRefreshKey(x => x + 1) }

  useEffect(() => {
    // 竞态守卫:切游戏时会连发两次(旧 slug 的 effect + 新 slug 的),旧请求晚返回会覆盖
    // 新值,导致状态栏计数串成全局数(实测:快照数量显示 7 实际当前游戏 3)。cleanup 作废旧请求。
    let stale = false
    const load = async () => {
      const scope = status.game_instance_id || status.game_slug || ''
      const mUrl = scope ? `${API}/mods?game_slug=${encodeURIComponent(scope)}` : `${API}/mods`
      const snUrl = scope ? `${API}/snapshots?game_slug=${encodeURIComponent(scope)}` : `${API}/snapshots`
      const m = await fetch(mUrl).then(r => r.json()).catch(() => [])
      const sn = await fetch(snUrl).then(r => r.json()).catch(() => [])
      if (!stale) setStatus(prev => ({ ...prev, mods: m.length, snaps: sn.length }))
    }
    load()
    return () => { stale = true }
  }, [refreshToggle, status.game_slug, status.game_instance_id])

  useEffect(() => {
    let stale = false
    const loadBg = async () => {
      if (status.bg) {
        const dataUrl = await window.modagent.getBgDataUrl(status.bg)
        if (!stale && dataUrl) {
          document.body.classList.add('has-bg')
          document.body.style.backgroundImage = `url("${dataUrl}")`
        }
      } else {
        applyEditionDefaultBackground()
      }
    }
    loadBg().catch(() => {
      if (stale) return
      applyEditionDefaultBackground()
    })
    return () => { stale = true }
  }, [status.bg])

  useEffect(() => {
    document.body.dataset.maPage = page
    return () => {
      delete document.body.dataset.maPage
    }
  }, [page])

  const onGameChange = async (g) => {
    const changeId = ++gameChangeSeq.current
    const localSlug = 'local_' + (g.name || 'game').toLowerCase()
      .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40)
    let slug = g.slug || localSlug
    const instanceId = g.game_instance_id || ''
    let gid = g.game_id

    setStatus(prev => ({
      ...prev,
      game: g.name,
      game_root: g.path,
      game_slug: slug,
      game_instance_id: instanceId,
      mods: 0,
      snaps: 0,
    }))
    if (g.adapted === false) {
      emitFeedback('warning', { source: 'game-change', game: g.name })
      toast(`已切换: ${g.name} · 开放模式——未特化适配,安装走通用规则,结果请自行核对`, 'error')
    } else {
      emitFeedback('notice', { source: 'game-change', game: g.name })
      toast(`游戏已切换: ${g.name}`)
    }

    if (!g.slug) {
      try {
        const r = await fetch(API + '/games/resolve?name=' + encodeURIComponent(g.name))
        const d = await r.json()
        if (d.slug) { slug = d.slug; gid = d.game_id }
      } catch (_) {}
    }
    if (changeId !== gameChangeSeq.current) return
    if (slug !== localSlug) {
      setStatus(prev => ({ ...prev, game_slug: slug }))
    }
    try {
      const [configResponse] = await Promise.all([
        fetch(API + '/config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            game_name: g.name,
            game_slug: slug,
            game_instance_id: instanceId,
            game_id: gid,
            game_root: g.path,
          }),
        }),
        fetch(API + '/chat/reset', { method: 'POST' }),
      ])
      if (!configResponse.ok) throw new Error(`config ${configResponse.status}`)
    } catch (_) {
      if (changeId === gameChangeSeq.current) {
        toast('游戏已在界面切换，但配置保存失败，请重试', 'error')
      }
    }
  }

  const onGameImport = async (payload) => {
    const response = await fetch(API + '/games/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok || !result.saved) {
      throw new Error(result.detail || result.error || '导入失败')
    }
    const norm = value => (value || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    const imported = result.game
    if (imported?.path) {
      setGames(previous => [
        imported,
        ...previous.filter(game => norm(game.path) !== norm(imported.path)),
      ])
    }
    if (imported) await onGameChange(imported)
    // Full launcher discovery can touch several large libraries. The manual
    // game is already authoritative, so refresh the remaining list without
    // making the import dialog wait for that scan.
    refreshGames().catch(() => {})
    return result
  }

  const toast = (msg, type = 'info') => {
    const id = `${Date.now()}-${++nextToastId.current}`
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000)
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {configured === false ? (
        <SetupPage onDone={() => setConfigured(true)} toast={toast} api={API} />
      ) : (
        <>
          <Sidebar page={page} onNav={setPage} status={status} />
          <main className="app-page-stage flex-1 overflow-hidden bg-surface-900">
            {status.online ? (
              <>
                <div aria-hidden={page !== 'chat'} className={`app-page-layer ${page === 'chat' ? 'is-active' : ''}`}><ChatPage status={status} games={games} onGameChange={onGameChange} onGameImport={onGameImport} onGamesRefresh={refreshGames} toast={toast} api={API} onRefresh={doRefresh} /></div>
                <div aria-hidden={page !== 'mods'} className={`app-page-layer ${page === 'mods' ? 'is-active' : ''}`}><ModsPage toast={toast} api={API} onRefresh={doRefresh} refreshKey={refreshKey} status={status} /></div>
                <div aria-hidden={page !== 'snaps'} className={`app-page-layer ${page === 'snaps' ? 'is-active' : ''}`}><SnapshotsPage toast={toast} api={API} status={status} onRefresh={doRefresh} /></div>
                <div aria-hidden={page !== 'settings'} className={`app-page-layer ${page === 'settings' ? 'is-active' : ''}`}><SettingsPage toast={toast} api={API} /></div>
                <div key={page} className={`app-page-atmosphere atmosphere-${page}`} aria-hidden="true" />
              </>
            ) : (
              <div className="h-full w-full flex items-center justify-center">
                <div className="flex flex-col items-center gap-4 text-center">
                  <div className="w-12 h-12 rounded-full border-2 border-cyber-cyan/20 border-t-cyber-cyan animate-spin" />
                  <div>
                    <div className="text-sm text-white">ModAgent 正在启动</div>
                    <div className="text-xs text-surface-500 mt-1">正在连接本地服务并读取游戏数据…</div>
                  </div>
                </div>
              </div>
            )}
          </main>
        </>
      )}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
        {toasts.map(t => <Toast key={t.id} {...t} />)}
      </div>
      {status.online && <DownloadPanel api={API} />}
    </div>
  )
}
