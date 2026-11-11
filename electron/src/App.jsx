import React, { useState, useEffect, useRef } from 'react'
import Sidebar from './components/Sidebar'
import ChatPage from './components/ChatPage'
import ModsPage from './components/ModsPage'
import SnapshotsPage from './components/SnapshotsPage'
import SettingsPage from './components/SettingsPage'
import PSharePage from './components/PSharePage'
import ReviewerConsole from './components/ReviewerConsole'
import PShareActivationOverlay from './components/PShareActivationOverlay'
import SetupPage from './components/SetupPage'
import Toast from './components/Toast'
import DownloadPanel from './components/DownloadPanel'
import { emitFeedback } from './feedback/feedbackBus'
import { applyEditionDefaultBackground } from '@edition'
import { tr } from './i18n'
import {readRuntimeStatus} from './runtimeStatus.mjs'
import {saveGameSelection, importGameSelection, verifyGameSelection} from './gameSelection.mjs'
import {requestLocalJson, LocalApiError, localApiFailure} from './components/localApi.mjs'

const exposedApiBase = window.modagent?.getApiBase?.()
const API = typeof exposedApiBase === 'string' ? exposedApiBase : 'http://127.0.0.1:18890'

export default function App() {
  const [page, setPage] = useState('chat')
  const [showPShareActivation, setShowPShareActivation] = useState(false)
  const [reviewerAccess, setReviewerAccess] = useState({ allowed: false, loading: true })
  const [status, setStatus] = useState({ online: false, game: '', mods: null, snaps: null, game_root: '', game_slug: '', game_instance_id: '', bg: null })
  const [games, setGames] = useState([])
  const [configured, setConfigured] = useState(null)
  const [connectionError, setConnectionError] = useState(null)
  const [language, setLanguage] = useState('zh-CN')
  const [toasts, setToasts] = useState([])
  const nextToastId = useRef(0)
  const gameChangeSeq = useRef(0)
  const gameChangeLock = useRef(false)
  const gameVerifyLock = useRef(false)
  const [gameTransition, setGameTransition] = useState(null)
  const [recoveredGameImport, setRecoveredGameImport] = useState(null)
  const updateRef = useState(0)[1]

  const refreshCounts = () => updateRef(x => x + 1)
  const refreshGames = async () => {
    const list = await requestLocalJson(API + '/games/detect', {}, {timeoutMs:120000})
    if (!Array.isArray(list)) throw new LocalApiError('LOCAL_API_INVALID_RESPONSE')
    setGames(list)
    return list
  }

  useEffect(() => {
    let cancelled = false
    let timer = null
    const controller = new AbortController()
    const check = async () => {
      if (gameChangeLock.current) return true
      const gameEpoch = gameChangeSeq.current
      try {
        const s = await readRuntimeStatus(API, {signal:controller.signal})
        if (gameEpoch !== gameChangeSeq.current || gameChangeLock.current) return true
        if (!cancelled) {
          setConnectionError(null)
          setStatus(prev => ({
            ...prev,
            online: true,
            game: s.game_name || '',
            game_root: s.game_root || '',
            game_slug: s.game_slug || '',
            game_instance_id: s.game_instance_id || '',
            bg: s.bg || null,
          }))
          if (s.language === 'en' || s.language === 'zh-CN') setLanguage(s.language)
          if (s.bg) document.body.classList.add('has-bg')
          setConfigured(Boolean(s.llm_set))
          if (!window.__gamesDetected) {
            window.__gamesDetected = true
            refreshGames().catch(() => { window.__gamesDetected = false })
          }
          return true
        }
      } catch (error) {
        if (gameEpoch !== gameChangeSeq.current || gameChangeLock.current) return true
        if (cancelled) return false
        setConnectionError(error)
      }
      if (cancelled) return false
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
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    let stale = false
    window.modagent?.getReviewerAccess?.()
      .then(result => { if (!stale) setReviewerAccess({ allowed: Boolean(result?.allowed), loading: false }) })
      .catch(() => { if (!stale) setReviewerAccess({ allowed: false, loading: false }) })
    return () => { stale = true }
  }, [])

  useEffect(() => {
    if (page === 'reviewer' && !reviewerAccess.loading && !reviewerAccess.allowed) setPage('chat')
  }, [page, reviewerAccess])

  const [refreshToggle, setRefreshToggle] = useState(0)
  const [refreshKey, setRefreshKey] = useState(0)
  const doRefresh = () => { setRefreshToggle(x => x + 1); setRefreshKey(x => x + 1) }

  useEffect(() => {
    // 竞态守卫:切游戏时会连发两次(旧 slug 的 effect + 新 slug 的),旧请求晚返回会覆盖
    // 新值,导致状态栏计数串成全局数(实测:快照数量显示 7 实际当前游戏 3)。cleanup 作废旧请求。
    let stale = false
    const controller = new AbortController()
    setStatus(prev => ({...prev, mods:null, snaps:null}))
    const load = async () => {
      const scope = status.game_instance_id || status.game_slug || ''
      const mUrl = scope ? `${API}/mods?game_slug=${encodeURIComponent(scope)}` : `${API}/mods`
      const snUrl = scope ? `${API}/snapshots?game_slug=${encodeURIComponent(scope)}` : `${API}/snapshots`
      const count = async url => {
        try {
          const items = await requestLocalJson(url, {signal:controller.signal})
          return Array.isArray(items) ? items.length : null
        } catch { return null }
      }
      const [mods, snaps] = await Promise.all([count(mUrl), count(snUrl)])
      if (!stale) setStatus(prev => ({ ...prev, mods, snaps }))
    }
    if (status.online) load()
    return () => { stale = true; controller.abort() }
  }, [refreshToggle, status.game_slug, status.game_instance_id, status.online])

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

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const onGameChange = async (g) => {
    if (gameChangeLock.current || !status.online) return false
    gameChangeLock.current = true
    ++gameChangeSeq.current
    setGameTransition({pending:true})
    try {
      const s = await saveGameSelection(API, g)
      setStatus(prev => ({...prev, game:s.game_name || g.name, game_root:s.game_root,
        game_slug:s.game_slug, game_instance_id:s.game_instance_id || '', mods:null, snaps:null}))
      gameChangeLock.current = false
      setGameTransition(null)
      emitFeedback(g.adapted === false ? 'warning' : 'notice', {source:'game-change',game:g.name})
      toast((language === 'en' ? 'Game selected: ' : '游戏已切换：') + g.name + (g.adapted === false
        ? (language === 'en' ? ' · Open mode: generic rules; verify installation results.' : ' · 开放模式：使用通用规则，请核对安装结果。') : ''))
      return true
    } catch (error) {
      // The config endpoint can have partially applied before a failed reply.
      // Do not unlock writes against a game whose active identity is uncertain.
      setGameTransition({pending:false,error,confirmedGame:error.confirmedGame})
      return false
    }
  }

  const onGameImport = async (payload) => {
    if (gameChangeLock.current || !status.online) throw new Error(language === 'en' ? '[GAME_IMPORT_BUSY] Wait for the current game operation or connection recovery.' : '[GAME_IMPORT_BUSY] 请等待当前游戏操作或连接恢复。')
    gameChangeLock.current = true
    ++gameChangeSeq.current
    setGameTransition({pending:true})
    try {
    const {result,status:s} = await importGameSelection(API, payload)
    const norm = value => (value || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    const imported = result.game
    if (imported?.path) {
      setGames(previous => [
        imported,
        ...previous.filter(game => norm(game.path) !== norm(imported.path)),
      ])
    }
    setStatus(prev => ({...prev,game:s.game_name || imported.name,game_root:s.game_root,
      game_slug:s.game_slug,game_instance_id:s.game_instance_id,mods:null,snaps:null}))
    gameChangeLock.current = false
    setGameTransition(null)
    // Full launcher discovery can touch several large libraries. The manual
    // game is already authoritative, so refresh the remaining list without
    // making the import dialog wait for that scan.
    refreshGames().catch(() => {})
    return result
    } catch (error) {
      if (!error?.confirmedGame && error?.code === 'LOCAL_API_HTTP' && [400,422].includes(error.status)) {
        gameChangeLock.current = false
        setGameTransition(null)
        throw new Error(language === 'en'
          ? '[GAME_IMPORT_REJECTED] The game directory or input was rejected. Check the actual installation folder and main executable, then retry.'
          : '[GAME_IMPORT_REJECTED] 游戏目录或输入未通过验证。请检查实际安装目录和主程序后重试。')
      }
      setGameTransition({pending:false,error,confirmedGame:error.confirmedGame,kind:'import'})
      throw new Error(language === 'en'
        ? '[GAME_IMPORT_UNCONFIRMED] The active game could not be verified. The entry may already be saved. Follow the recovery instructions; do not import again yet.'
        : '[GAME_IMPORT_UNCONFIRMED] 当前游戏核验未通过，条目可能已经保存。请按页面恢复提示处理，暂勿重复导入。')
    }
  }

  const recheckSavedGame = async () => {
    const game = gameTransition?.confirmedGame
    if (!game || gameVerifyLock.current) return
    gameVerifyLock.current = true
    setGameTransition(previous => ({...previous, verifying:true}))
    try {
      const s = await verifyGameSelection(API, game)
      setStatus(previous => ({...previous, online:true, game:s.game_name || game.name,
        game_root:s.game_root, game_slug:s.game_slug, game_instance_id:s.game_instance_id || '', mods:null, snaps:null}))
      ++gameChangeSeq.current
      gameChangeLock.current = false
      if (gameTransition.kind === 'import') setRecoveredGameImport({...game})
      setGameTransition(null)
      doRefresh()
      refreshGames().catch(() => {})
      toast((language === 'en' ? 'Active game verified: ' : '已核验当前游戏：') + (s.game_name || game.name))
    } catch (error) {
      setGameTransition({pending:false,error,confirmedGame:game,verifying:false,kind:gameTransition.kind})
    } finally { gameVerifyLock.current = false }
  }

  const toast = (msg, type = 'info') => {
    const id = `${Date.now()}-${++nextToastId.current}`
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000)
  }

  return (
    <div className={`app-shell flex h-screen overflow-hidden ${
      configured === false ? 'is-setup' : 'is-workspace'
    }`}>
      {configured === false ? (
        <SetupPage onDone={() => setConfigured(true)} toast={toast} api={API} language={language} onLanguageChange={setLanguage} />
      ) : (
        <>
          <Sidebar page={page} onNav={setPage} status={status} reviewerAllowed={reviewerAccess.allowed} language={language} />
          <main className="app-page-stage relative flex-1 overflow-hidden bg-surface-900">
            {configured === true ? (
              <>
                <div className="contents" inert={!status.online || gameTransition ? '' : undefined}>
                <div aria-hidden={page !== 'chat'} className={`app-page-layer ${page === 'chat' ? 'is-active' : ''}`}><ChatPage status={status} games={games} onGameChange={onGameChange} onGameImport={onGameImport} recoveredGameImport={recoveredGameImport} onGamesRefresh={refreshGames} toast={toast} api={API} onRefresh={doRefresh} language={language} /></div>
                <div aria-hidden={page !== 'mods'} className={`app-page-layer ${page === 'mods' ? 'is-active' : ''}`}><ModsPage toast={toast} api={API} onRefresh={doRefresh} refreshKey={refreshKey} status={status} language={language} /></div>
                <div aria-hidden={page !== 'snaps'} className={`app-page-layer ${page === 'snaps' ? 'is-active' : ''}`}><SnapshotsPage toast={toast} api={API} status={status} onRefresh={doRefresh} language={language} /></div>
                <div aria-hidden={page !== 'settings'} className={`app-page-layer ${page === 'settings' ? 'is-active' : ''}`}><SettingsPage toast={toast} api={API} language={language} onLanguageChange={setLanguage} onStartSharePlan={(request) => {
                  setPage('chat')
                  window.dispatchEvent(new CustomEvent('modagent:share-plan', {
                    detail: typeof request === 'string' ? { share: request } : request,
                  }))
                }} onPShareActivated={() => {
                  setPage('pshare')
                  setShowPShareActivation(true)
                }} /></div>
                <div aria-hidden={page !== 'pshare'} className={`app-page-layer ${page === 'pshare' ? 'is-active' : ''}`}><PSharePage toast={toast} language={language} /></div>
                {reviewerAccess.allowed && <div aria-hidden={page !== 'reviewer'} className={`app-page-layer ${page === 'reviewer' ? 'is-active' : ''}`}><ReviewerConsole toast={toast} /></div>}
                <div key={page} className={`app-page-atmosphere atmosphere-${page}`} aria-hidden="true" />
                </div>
                {gameTransition && <div role="alert" className="absolute inset-0 z-50 flex items-center justify-center bg-surface-900/90 p-6">
                  <div className="max-w-md text-center space-y-3">
                    {gameTransition.pending ? <p>{language === 'en' ? 'Saving and verifying the selected game…' : '正在保存并核验所选游戏…'}</p> : <>
                      <p>[GAME_SELECTION_UNCONFIRMED] {localApiFailure(gameTransition.error, language)}</p>
                      <p className="text-sm">{gameTransition.confirmedGame
                        ? (language === 'en' ? 'The save was acknowledged, but the active game is not verified. Recheck reads the current state without saving or importing again. Editing stays locked until it matches.' : '后台已确认保存，但尚未核验当前游戏。重新核验只读取状态，不会再次保存或导入；匹配前继续锁定操作。')
                        : (language === 'en' ? 'The active game is uncertain. Editing is locked to prevent changes to the wrong game. Restart ModAgent and check the selected game before continuing.' : '无法确认后台当前游戏，已锁定操作以免修改错误的游戏。请重启 ModAgent，核对所选游戏后继续。')}</p>
                      {gameTransition.confirmedGame && <button className="btn-cyber" disabled={gameTransition.verifying} onClick={recheckSavedGame}>
                        {gameTransition.verifying ? (language === 'en' ? 'Verifying…' : '正在核验…') : (language === 'en' ? 'Recheck active game' : '重新核验当前游戏')}
                      </button>}
                    </>}
                  </div>
                </div>}
                {!status.online && <div role="alert" className="absolute inset-0 z-50 flex items-center justify-center bg-surface-900/90 p-6">
                  <div className="max-w-md text-center space-y-3">
                    <p>[APP_CONNECTION_FAILED] {localApiFailure(connectionError, language)}</p>
                    <p className="text-sm text-surface-500">{language === 'en'
                      ? 'Reconnecting automatically. This page is temporarily locked; your draft stays here. A running operation may still be active in the backend.'
                      : '正在自动重连，当前页面暂时锁定，草稿仍保留。正在执行的操作可能仍在后台运行。'}</p>
                  </div>
                </div>}
              </>
            ) : (
              <div className="h-full w-full flex items-center justify-center">
                <div className="flex flex-col items-center gap-4 text-center">
                  <div className="w-12 h-12 rounded-full border-2 border-cyber-cyan/20 border-t-cyber-cyan animate-spin" />
                  <div>
                    <div className="text-sm text-white">{tr(language, 'startingApp')}</div>
                    <div className="text-xs text-surface-500 mt-1">{tr(language, 'startingDetail')}</div>
                    {connectionError && <div role="alert" className="text-xs text-cyber-yellow mt-3 max-w-md">
                      [APP_CONNECTION_FAILED] {localApiFailure(connectionError, language)}
                      <p className="mt-2">{language === 'en' ? 'Retrying automatically. Existing configuration has not been reset.' : '正在自动重连，未重置已有配置。'}</p>
                    </div>}
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
      {status.online && <DownloadPanel api={API} language={language} />}
      {showPShareActivation && <PShareActivationOverlay onClose={() => setShowPShareActivation(false)} />}
    </div>
  )
}
