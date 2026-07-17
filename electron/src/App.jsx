import React, { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import ChatPage from './components/ChatPage'
import ModsPage from './components/ModsPage'
import SnapshotsPage from './components/SnapshotsPage'
import SettingsPage from './components/SettingsPage'
import SetupPage from './components/SetupPage'
import Toast from './components/Toast'
import DownloadPanel from './components/DownloadPanel'
import defaultWallpaper from './assets/default-wallpaper.png'

const exposedApiBase = window.modagent?.getApiBase?.()
const API = typeof exposedApiBase === 'string' ? exposedApiBase : 'http://127.0.0.1:18890'

export default function App() {
  const [page, setPage] = useState('chat')
  const [status, setStatus] = useState({ online: false, game: '', mods: 0, snaps: 0, game_root: '', game_slug: '', bg: null })
  const [games, setGames] = useState([])
  const [configured, setConfigured] = useState(null)
  const [toasts, setToasts] = useState([])
  const updateRef = useState(0)[1]

  const refreshCounts = () => updateRef(x => x + 1)

  useEffect(() => {
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
            bg: s.bg || null,
          }))
          document.body.classList.add('has-bg')
          setConfigured(s.api_key_set && s.tavily_set && s.llm_set)
          if (!games.length && !window.__gamesDetected) {
            window.__gamesDetected = true
            fetch(API + '/games/detect').then(r => r.json()).then(g => {
              if (Array.isArray(g) && g.length) setGames(g)
            }).catch(() => { window.__gamesDetected = false })
          }
          return
        }
      } catch (_) {}
      setStatus(prev => ({ ...prev, online: false }))
    }
    check()
    const interval = setInterval(check, 15000)
    return () => clearInterval(interval)
  }, [])

  const [refreshToggle, setRefreshToggle] = useState(0)
  const [refreshKey, setRefreshKey] = useState(0)
  const doRefresh = () => { setRefreshToggle(x => x + 1); setRefreshKey(x => x + 1) }

  useEffect(() => {
    // 竞态守卫:切游戏时会连发两次(旧 slug 的 effect + 新 slug 的),旧请求晚返回会覆盖
    // 新值,导致状态栏计数串成全局数(实测:快照数量显示 7 实际当前游戏 3)。cleanup 作废旧请求。
    let stale = false
    const load = async () => {
      const slug = status.game_slug || ''
      const mUrl = slug ? `${API}/mods?game_slug=${encodeURIComponent(slug)}` : `${API}/mods`
      const snUrl = slug ? `${API}/snapshots?game_slug=${encodeURIComponent(slug)}` : `${API}/snapshots`
      const m = await fetch(mUrl).then(r => r.json()).catch(() => [])
      const sn = await fetch(snUrl).then(r => r.json()).catch(() => [])
      if (!stale) setStatus(prev => ({ ...prev, mods: m.length, snaps: sn.length }))
    }
    load()
    return () => { stale = true }
  }, [refreshToggle, status.game_slug])

  useEffect(() => {
    let stale = false
    const loadBg = async () => {
      if (status.bg) {
        const dataUrl = await window.modagent.getBgDataUrl(status.bg)
        if (!stale && dataUrl) {
          document.body.classList.add('has-bg')
          document.body.classList.remove('default-bg')
          document.body.style.backgroundImage = `url("${dataUrl}")`
        }
      } else {
        document.body.classList.add('has-bg', 'default-bg')
        document.body.style.backgroundImage = `url("${defaultWallpaper}")`
      }
    }
    loadBg().catch(() => {
      if (stale) return
      document.body.classList.add('has-bg', 'default-bg')
      document.body.style.backgroundImage = `url("${defaultWallpaper}")`
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
    let slug = g.slug
    let gid = g.game_id
    if (!slug) {
      try {
        const r = await fetch(API + '/games/resolve?name=' + encodeURIComponent(g.name))
        const d = await r.json()
        if (d.slug) { slug = d.slug; gid = d.game_id }
      } catch (_) {}
    }
    // Nexus 没有该游戏 → 生成本地隔离键，保证每个游戏数据互相隔离（否则空 slug 会串数据）
    if (!slug) {
      slug = 'local_' + (g.name || 'game').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40)
    }
    await fetch(API + '/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game_name: g.name, game_slug: slug, game_id: gid, game_root: g.path })
    })
    await fetch(API + '/chat/reset', { method: 'POST' })
    setStatus(prev => ({ ...prev, game: g.name, game_root: g.path, game_slug: slug }))
    if (g.adapted === false) {
      toast(`已切换: ${g.name} · 开放模式——未特化适配,安装走通用规则,结果请自行核对`, 'error')
    } else {
      toast(`游戏已切换: ${g.name}`)
    }
  }

  const toast = (msg, type = 'info') => {
    const id = Date.now()
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
            <div aria-hidden={page !== 'chat'} className={`app-page-layer ${page === 'chat' ? 'is-active' : ''}`}><ChatPage status={status} games={games} onGameChange={onGameChange} toast={toast} api={API} onRefresh={doRefresh} /></div>
            <div aria-hidden={page !== 'mods'} className={`app-page-layer ${page === 'mods' ? 'is-active' : ''}`}><ModsPage toast={toast} api={API} onRefresh={doRefresh} refreshKey={refreshKey} status={status} /></div>
            <div aria-hidden={page !== 'snaps'} className={`app-page-layer ${page === 'snaps' ? 'is-active' : ''}`}><SnapshotsPage toast={toast} api={API} status={status} onRefresh={doRefresh} /></div>
            <div aria-hidden={page !== 'settings'} className={`app-page-layer ${page === 'settings' ? 'is-active' : ''}`}><SettingsPage toast={toast} api={API} /></div>
            <div key={page} className={`app-page-atmosphere atmosphere-${page}`} aria-hidden="true" />
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
