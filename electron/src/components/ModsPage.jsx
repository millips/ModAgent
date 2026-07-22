import React, { useState, useEffect } from 'react'
import { Search, Download, CheckSquare, Trash2, RefreshCw, AlertTriangle, Archive, RotateCcw, XCircle, FolderInput, Link2 } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'

const MOCK_MODS = [
  { id: '107', name: 'Cyber Engine Tweaks', name_cn: 'CET 脚本框架', version: '1.32.2', latest: null, category: '框架', desc: '所有脚本 mod 的前置依赖', size: '2.3MB', hasConflict: false, disabled: false },
  { id: '1511', name: 'redscript', name_cn: 'redscript 编译器', version: '0.5.16', latest: null, category: '框架', desc: '编译 .reds 脚本文件', size: '1.1MB', hasConflict: false, disabled: false },
  { id: '2380', name: 'RED4ext', name_cn: 'RED4ext 脚本扩展', version: '1.24.0', latest: null, category: '框架', desc: 'C++ 插件加载器', size: '0.8MB', hasConflict: false, disabled: false },
  { id: '4198', name: 'ArchiveXL', name_cn: 'ArchiveXL 资源加载', version: '1.14.0', latest: '1.16.2', category: '框架', desc: '扩展资源加载功能', size: '1.5MB', hasConflict: false, disabled: false },
  { id: '4199', name: 'TweakXL', name_cn: 'TweakXL 配置引擎', version: '1.5.0', latest: '1.7.3', category: '框架', desc: 'TweakDB 修改引擎', size: '2.0MB', hasConflict: false, disabled: false },
  { id: '7780', name: 'Codeware', name_cn: 'Codeware 函数库', version: '1.9.0', latest: null, category: '框架', desc: 'Lua 脚本函数扩展库', size: '3.4MB', hasConflict: false, disabled: false },
  { id: '7054', name: 'VTK Vanilla HD Body', name_cn: 'VTK 高清身体模型', version: '2.0', latest: '2.2', category: '模型', desc: '女性V高清全身模型替换', size: '1.2GB', hasConflict: false, disabled: false },
  { id: '4654', name: 'EBB Body', name_cn: 'EBB 身体模型', version: '1.3', latest: null, category: '模型', desc: 'Enhanced Big Booty 身体模型', size: '780MB', hasConflict: true, disabled: false },
  { id: '5408', name: 'Vanilla Clothes Refits', name_cn: '原版服装适配', version: '1.0', latest: null, category: '服装', desc: '原版服装对身体模型的适配', size: '45MB', hasConflict: false, disabled: true },
  { id: '15151', name: 'ANGEL Body', name_cn: 'ANGEL 身体模型', version: '2.0', latest: null, category: '模型', desc: 'ANGEL 身体替换模型', size: '650MB', hasConflict: true, disabled: false },
  { id: '2987', name: 'Virtual Atelier', name_cn: '虚拟商店', version: '1.2', latest: null, category: '功能', desc: '游戏内在线Mod商店', size: '5.2MB', hasConflict: false, disabled: false },
  { id: '5265', name: 'Equipment-EX', name_cn: '装备系统扩展', version: '1.2.0', latest: null, category: '框架', desc: '独立装备槽位系统', size: '3.1MB', hasConflict: false, disabled: false },
]

const FILTERS = ['全部', '可更新', '已禁用']

export default function ModsPage({ toast, api, onRefresh, refreshKey, status }) {
  const [mods, setMods] = useState([])
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('全部')
  const [statusFilter, setStatusFilter] = useState('全部')
  const [selected, setSelected] = useState(new Set())
  const [hovered, setHovered] = useState(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(null)
  const [dependencyGate, setDependencyGate] = useState(null)
  const [batchDelete, setBatchDelete] = useState(null)
  const [batchBusy, setBatchBusy] = useState(false)
  const [actionLock, setActionLock] = useState(null)
  const [showDownload, setShowDownload] = useState(false)
  const [dlUrl, setDlUrl] = useState('')
  const [dlBusy, setDlBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [binding, setBinding] = useState(false)

  useEffect(() => { loadFromApi() }, [refreshKey, status?.game_slug])

  const loadFromApi = async () => {
    try {
      const slug = status?.game_slug || ''
      const r = await fetch(slug ? `${api}/mods?game_slug=${encodeURIComponent(slug)}` : `${api}/mods`)
      if (!r.ok) throw new Error(`mods request failed: ${r.status}`)
      const apiMods = await r.json()
      if (!Array.isArray(apiMods)) throw new Error('mods response is not an array')
      setMods(apiMods.map(m => ({
        id: m.id || '', name: m.name || m.id, name_cn: m.name || '', version: m.version || '?',
        latest: null, category: '', desc: `ID: ${m.id}`, size: '',
        hasConflict: false, disabled: !!m.disabled,
      })))
    } catch (_) { toast('加载 Mod 列表失败', 'error') }
  }

  const reconcileMods = async () => {
    toast('对账中...')
    try {
      const slug = status?.game_slug || ''
      const r = await fetch(`${api}/mods/reconcile?game_slug=${encodeURIComponent(slug)}`, { method: 'POST' })
      const d = await r.json()
      if (d.issues?.length) {
        const names = d.issues.slice(0, 3).map(i => `${i.name}(${i.problem})`).join('、')
        emitFeedback('warning', { source: 'mod-reconcile', count: d.issues.length })
        toast(`发现 ${d.issues.length}/${d.checked} 个 mod 账实不符: ${names}${d.issues.length > 3 ? ' 等' : ''}`, 'error')
      } else { emitFeedback('notice', { source: 'mod-reconcile' }); toast(`对账完成: ${d.checked} 个 mod 账实一致`) }
    } catch (_) { emitFeedback('error', { source: 'mod-reconcile' }); toast('对账失败', 'error') }
  }

  // 检查更新：跑 mod_update_check，把"最新版本"标到对应 mod 上 → 可更新筛选/更新按钮变真
  const checkUpdates = async () => {
    setChecking(true)
    toast('检查更新中...')
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 60000)
    try {
      const r = await fetch(api + '/tool/mod_update_check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
        signal: controller.signal,
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) throw new Error(data.error)
      const ups = data.updates_available || []
      const map = {}
      ups.forEach(u => { map[String(u.mod_id)] = u.latest })
      setMods(prev => prev.map(m => ({ ...m, latest: map[String(m.id)] || null })))
      emitFeedback('notice', { source: 'update-check', count: ups.length })
      const failed = data.failed_checks?.length || 0
      const checked = data.checked_nexus || 0
      if (failed) toast(`检查完成：${checked} 个成功，${failed} 个暂时无法查询${ups.length ? `，发现 ${ups.length} 个更新` : ''}`, 'error')
      else toast(ups.length ? `发现 ${ups.length} 个可更新` : `检查完成：${checked} 个 Nexus Mod 均为最新`)
    } catch (error) {
      emitFeedback('error', { source: 'update-check' })
      toast(error?.name === 'AbortError' ? '检查超时，已解除按钮锁定；请稍后重试' : '检查更新失败', 'error')
    } finally {
      window.clearTimeout(timeoutId)
      setChecking(false)
    }
  }

  const bindRecognized = async () => {
    setBinding(true)
    toast('正在把本地 Mod 对齐到维护来源…')
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 120000)
    try {
      const response = await fetch(api + '/tool/mod_source_align', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force_refresh: true }), signal: controller.signal,
      })
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error) throw new Error(result.error)
      const summary = result.summary || {}
      emitFeedback('notice', { source: 'source-align', count: summary.bound || 0 })
      toast(`绑定完成：成功 ${summary.bound || 0}，歧义 ${summary.ambiguous || 0}，未匹配 ${summary.unmatched || 0}`)
      loadFromApi()
      onRefresh?.()
    } catch (error) {
      emitFeedback('error', { source: 'source-align' })
      toast(error?.name === 'AbortError' ? '绑定耗时过长，已保留现有结果，可稍后继续' : '来源绑定失败', 'error')
    } finally {
      window.clearTimeout(timeoutId)
      setBinding(false)
    }
  }

  // 下载新 Mod：粘贴 GitHub/Thunderstore/GameBanana 链接 → 下载（+可选安装）
  const doDownload = async () => {
    const url = dlUrl.trim()
    if (!url) return
    setDlBusy(true)
    try {
      const r = await fetch(api + '/tool/download_from_url', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) { emitFeedback('error', { source: 'download' }); toast(friendlyErr(data.error), 'error'); setDlBusy(false); return }
      if (data.already_installed) {
        emitFeedback('notice', { source: 'download-dedup', name: data.name || '' })
        toast(`${data.name || '该 Mod'} 已安装，已跳过重复下载`)
        setShowDownload(false); setDlUrl(''); setDlBusy(false); loadFromApi(); onRefresh?.(); return
      }
      toast(`已下载 ${data.name || ''}，正在安装...`)
      emitFeedback('install-start', { source: 'direct-install', name: data.name || '' })
      const r2 = await fetch(api + '/tool/mod_install', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ local_path: data.local_path }),
      })
      const d2 = await r2.json()
      const data2 = JSON.parse(d2.result || '{}')
      if (data2.error) { emitFeedback('error', { source: 'install' }); toast(friendlyErr(data2.error), 'error') }
      else { emitFeedback('install-complete', { name: data.name || '' }); toast(`已安装 ${data.name || ''}（${(data2.files_installed || []).length} 文件）`); loadFromApi(); onRefresh?.() }
      setShowDownload(false); setDlUrl('')
    } catch (_) { emitFeedback('error', { source: 'download' }); toast('下载失败', 'error') }
    setDlBusy(false)
  }

  const friendlyErr = (raw) => {
    const s = String(raw || '')
    if (s.includes('Chrome CDP') || s.includes('浏览器自动化服务')) return '请重启 ModAgent，程序会自动启动 Edge、Chrome 或 Brave'
    if (s.includes('API Key') || s.includes('apikey')) return 'API 密钥无效，请在设置中检查'
    if (s.includes('game_root') || s.includes('游戏目录')) return '请先选择游戏目录'
    if (s.length > 80) return '操作失败，请重试'
    return s
  }

  const filtered = mods.filter(m => {
    if (search && !m.name.toLowerCase().includes(search.toLowerCase()) && !m.name_cn.includes(search)) return false
    if (catFilter !== '全部' && m.category !== catFilter) return false
    if (statusFilter === '可更新' && !m.latest) return false
    if (statusFilter === '有冲突' && !m.hasConflict) return false
    if (statusFilter === '已禁用' && !m.disabled) return false
    return true
  })

  const toggleSelect = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set())
    else setSelected(new Set(filtered.map(m => m.id)))
  }

  const handleDelete = async (mod) => {
    // 先向后端拿卸载预览(不带 confirmed)——确认前就展示影响(将删文件数/是否退订/依赖警告)
    try {
      const r = await fetch(api + '/tool/mod_uninstall', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mod_id: mod.id })
      })
      const d = await r.json()
      const preview = JSON.parse(d.result || '{}')
      setShowDeleteConfirm({ ...mod, preview })
    } catch (e) {
      setShowDeleteConfirm({ ...mod, preview: null })   // 预览失败仍允许确认(降级,后端仍会二次守门)
    }
  }

  const confirmDelete = async () => {
    const mod = showDeleteConfirm
    setShowDeleteConfirm(null)
    setActionLock(mod.id)
    toast('卸载中...')
    try {
      const r = await fetch(api + '/tool/mod_uninstall', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mod_id: mod.id, confirmed: true })
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) { emitFeedback('error', { source: 'uninstall' }); toast(friendlyErr(data.error), 'error') }
      else {
        emitFeedback('remove-complete', { modId: mod.id, name: mod.name })
        toast(`${mod.name || mod.id} 已卸载 (${data.removed || 0} 个文件)`)
        loadFromApi()
        onRefresh?.()
        if (data.dependents_warned?.length) toast(`警告: ${data.dependents_warned.join(', ')} 依赖此 Mod`, 'warn')
      }
    } catch (e) { emitFeedback('error', { source: 'uninstall' }); toast('卸载失败', 'error') }
    setActionLock(null)
  }

  const toggleMod = async (mod, confirmed = false) => {
    const enabling = !!mod.disabled
    const action = enabling ? 'mod_enable' : 'mod_disable'
    setActionLock(mod.id)
    if (!confirmed) toast(`${enabling ? '检查启用条件' : '检查依赖影响'}：${mod.name}...`)
    try {
      const r = await fetch(api + '/tool/' + action, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mod_id: mod.id, ...(confirmed ? { confirmed: true } : {}) })
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) {
        emitFeedback('error', { source: action })
        toast(friendlyErr(data.error), 'error')
      } else if (data.blocked || data.requires_confirmation) {
        setDependencyGate({ mod, action, enabling, data })
        emitFeedback(data.blocked || !enabling ? 'warning' : 'notice', {
          source: 'dependency-gate', modId: mod.id,
          count: (data.dependencies || data.dependents || data.missing_dependencies || []).length,
        })
      } else {
        const affected = (data.enabled_mods || data.disabled_mods || []).length
        emitFeedback(enabling ? 'enable' : 'disable', { source: action, modId: mod.id, count: affected })
        toast(`${mod.name} 已${enabling ? '启用' : '禁用'}${affected > 1 ? `，共处理 ${affected} 个 Mod` : ''}`)
        await loadFromApi()
        onRefresh?.()
      }
    } catch (e) {
      emitFeedback('error', { source: action })
      toast('操作失败', 'error')
    }
    setActionLock(null)
  }

  const confirmDependencyToggle = async () => {
    const gate = dependencyGate
    if (!gate || gate.data.blocked) return
    setDependencyGate(null)
    await toggleMod(gate.mod, true)
  }

  const previewBatchDelete = async () => {
    const targets = mods.filter(mod => selected.has(mod.id))
    if (!targets.length || batchBusy) return
    setBatchBusy(true)
    toast(`正在核对 ${targets.length} 个 Mod 的卸载影响...`)
    try {
      const items = []
      for (const mod of targets) {
        const r = await fetch(api + '/tool/mod_uninstall', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: mod.id }),
        })
        const d = await r.json()
        const preview = JSON.parse(d.result || '{}')
        if (preview.error || !preview.requires_confirmation) throw new Error(preview.error || `无法预览 ${mod.name}`)
        items.push({ mod, preview })
      }
      setBatchDelete({ items })
      emitFeedback('warning', { source: 'batch-uninstall-preview', count: items.length })
    } catch (error) {
      emitFeedback('error', { source: 'batch-uninstall-preview' })
      toast(friendlyErr(error?.message || '批量卸载预览失败'), 'error')
    } finally {
      setBatchBusy(false)
    }
  }

  const confirmBatchDelete = async () => {
    const plan = batchDelete
    if (!plan || batchBusy) return
    setBatchDelete(null)
    setBatchBusy(true)
    const succeeded = []
    const failed = []
    for (const item of plan.items) {
      try {
        const r = await fetch(api + '/tool/mod_uninstall', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: item.mod.id, confirmed: true }),
        })
        const d = await r.json()
        const data = JSON.parse(d.result || '{}')
        if (data.error) failed.push(item.mod.name)
        else succeeded.push(item.mod.id)
      } catch (_) {
        failed.push(item.mod.name)
      }
    }
    if (succeeded.length) {
      emitFeedback('remove-complete', { source: 'batch-uninstall', count: succeeded.length })
      setSelected(prev => new Set([...prev].filter(id => !succeeded.includes(id))))
      await loadFromApi()
      onRefresh?.()
    }
    if (failed.length) {
      emitFeedback('error', { source: 'batch-uninstall', count: failed.length })
      toast(`已卸载 ${succeeded.length} 个；${failed.length} 个失败：${failed.slice(0, 3).join('、')}`, 'error')
    } else {
      toast(`已卸载 ${succeeded.length} 个 Mod`)
    }
    setBatchBusy(false)
  }

  const totalSize = mods.reduce((sum, m) => {
    const num = parseFloat(m.size)
    const unit = m.size.includes('GB') ? 1024 : m.size.includes('MB') ? 1 : 0.001
    return sum + num * unit
  }, 0)

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Top toolbar */}
      <div className="p-3 border-b border-surface-600 bg-surface-800 space-y-2">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-500" />
            <input
              className="input-cyber pl-9"
              placeholder="搜索 Mod 名称..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={`px-3 py-1.5 rounded-md text-xs transition-all ${statusFilter === f ? 'bg-cyber-blue/20 text-cyber-cyan border border-cyber-cyan/30' : 'text-surface-500 hover:text-white'}`}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap justify-end gap-1 ml-auto">
            <button className="btn-ghost flex items-center gap-1" onClick={reconcileMods}
              title="校验每个已装 mod 记录的文件是否还在磁盘上,揪出空账/缺文件">
              对账
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={checkUpdates} disabled={checking}>
              <RefreshCw size={14} className={checking ? 'animate-spin' : ''} /> 检查更新
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={bindRecognized} disabled={binding || checking}
              title="将扫描到的本地 Mod 自动绑定到可信的 Nexus、Thunderstore 或 Steam 维护页，之后可统一检查和更新">
              <Link2 size={14} className={binding ? 'animate-pulse' : ''} /> {binding ? '绑定中' : '一键绑定'}
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={loadFromApi}>
              刷新
            </button>
            <button className="btn-cyber flex items-center gap-1.5" onClick={() => setShowDownload(true)}>
              <Download size={14} /> 下载新 Mod
            </button>
            <button className="btn-ghost flex items-center gap-1" title="打开投放文件夹：把手动下载的 mod(三宫六院/3DM/网盘等)拖进去，再让 ModAgent 扫描安装"
              onClick={async () => {
                try {
                  const r = await fetch(api + '/dropbox/open', { method: 'POST' })
                  const d = await r.json()
                  if (d.ok) { emitFeedback('notice', { source: 'dropbox' }); toast('已打开投放文件夹，把下载好的 mod 拖进去，再让 ModAgent 扫描安装') }
                  else { emitFeedback('error', { source: 'dropbox' }); toast('打开失败: ' + (d.error || ''), 'error') }
                } catch (e) { emitFeedback('error', { source: 'dropbox' }); toast('打开失败', 'error') }
              }}>
              <FolderInput size={14} /> 投放文件夹
            </button>
            <button className="btn-ghost flex items-center gap-1" title="打开 ModAgent 为当前游戏保存下载包的目录"
              onClick={async () => {
                try {
                  const r = await fetch(api + '/downloads/open', { method: 'POST' })
                  const d = await r.json()
                  if (d.ok) { emitFeedback('notice', { source: 'downloads' }); toast('已打开 Mod 文件夹') }
                  else { emitFeedback('error', { source: 'downloads' }); toast('打开失败: ' + (d.error || ''), 'error') }
                } catch (e) { emitFeedback('error', { source: 'downloads' }); toast('打开失败', 'error') }
              }}>
              <FolderInput size={14} /> Mod 文件夹
            </button>
            <button className="btn-ghost flex items-center gap-1" title="打开独立 Mod 管理器、加载器等工具的受控解压目录"
              onClick={async () => {
                try {
                  const r = await fetch(api + '/tools/open', { method: 'POST' })
                  const d = await r.json()
                  if (d.ok) { emitFeedback('notice', { source: 'tools' }); toast('已打开工具目录') }
                  else { emitFeedback('error', { source: 'tools' }); toast('打开失败: ' + (d.error || ''), 'error') }
                } catch (e) { emitFeedback('error', { source: 'tools' }); toast('打开失败', 'error') }
              }}>
              <FolderInput size={14} /> 工具目录
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={toggleAll}>
              <CheckSquare size={14} /> {selected.size === filtered.length ? '取消全选' : '全选'}
            </button>
          </div>
        </div>
      </div>

      {/* Mod list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map((mod, i) => (
          <div
            key={mod.id}
            onMouseEnter={() => setHovered(mod.id)}
            onMouseLeave={() => setHovered(null)}
            className={`flex items-center gap-3 px-4 py-2.5 border-b border-surface-700/50 transition-all duration-150 animate-fade-in
              ${mod.hasConflict ? 'border-l-2 border-l-cyber-red' : ''}
              ${mod.disabled ? 'opacity-40' : ''}
              ${hovered === mod.id ? 'bg-surface-700/50' : ''}`}
            style={{ animationDelay: `${i * 30}ms` }}
          >
            {/* Checkbox */}
            <input
              type="checkbox"
              checked={selected.has(mod.id)}
              onChange={() => toggleSelect(mod.id)}
              className="w-4 h-4 rounded accent-cyber-cyan cursor-pointer"
            />

            {/* Icon */}
            <div className="w-10 h-10 rounded-md bg-surface-700 flex items-center justify-center shrink-0">
              <Archive size={20} className="text-surface-500" />
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-sm font-medium truncate ${mod.disabled ? 'line-through text-surface-500' : 'text-white'}`}>
                  {mod.name_cn || mod.name}
                </span>
                {!mod.disabled && <span className="text-xs text-surface-500 truncate">{mod.name}</span>}
                <span className={`text-xs ${mod.disabled ? 'text-surface-500' : 'text-cyber-cyan/70'} font-mono`}>v{mod.version}</span>
                {mod.latest && !mod.disabled && (
                  <span className="relative flex items-center gap-1 text-xs text-cyber-orange">
                    <span className="w-2 h-2 rounded-full bg-cyber-orange shadow-[0_0_4px_#db6d28]"></span>
                    v{mod.latest}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[11px] text-surface-500">{mod.desc}</span>
              </div>
            </div>

            {/* Tags */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="badge-cyan text-[10px]">{mod.category}</span>
              <span className="text-[10px] text-surface-500">{mod.size}</span>
            </div>

            {/* Actions - show on hover */}
            <div className={`flex items-center gap-1 shrink-0 transition-opacity duration-75 ${hovered === mod.id || mod.disabled ? 'opacity-100' : 'opacity-0'}`}>
              {mod.latest && (
                <button disabled={actionLock === mod.id}
                  onClick={async () => {
                    setActionLock(mod.id)
                    toast(`更新 ${mod.name}...`)
                    emitFeedback('install-start', { source: 'mod-update', modId: mod.id })
                    try {
                      const r = await fetch(api + '/tool/mod_update', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ mod_id: mod.id })
                      })
                      const d = await r.json()
                      const data = JSON.parse(d.result || '{}')
                      if (data.error) { emitFeedback('error', { source: 'mod-update' }); toast(friendlyErr(data.error), 'error') }
                      else { emitFeedback('install-complete', { source: 'mod-update', modId: mod.id }); toast(`${mod.name} 已更新`); loadFromApi(); onRefresh?.() }
                    } catch (e) { emitFeedback('error', { source: 'mod-update' }); toast('更新失败', 'error') }
                    setActionLock(null)
                  }} className="btn-ghost p-1.5" title="更新">
                  {actionLock === mod.id ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} className="text-cyber-cyan" />}
                </button>
              )}
              <button disabled={actionLock === mod.id}
                onClick={() => toggleMod(mod)}
                className={`btn-ghost p-1.5 flex items-center gap-1 ${mod.disabled ? 'text-cyber-cyan px-2' : ''}`} title={mod.disabled ? '启用' : '禁用'}>
                {mod.disabled ? <><RotateCcw size={14} /><span className="text-xs">启用</span></> : <XCircle size={14} />}
              </button>
              <button disabled={actionLock === mod.id} onClick={() => handleDelete(mod)} className="btn-danger p-1.5" title="删除">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {filtered.length === 0 && mods.length === 0 && (
          <div className="mods-empty-state flex flex-col items-center justify-center py-20 text-surface-500">
            <Archive size={32} className="mb-2 opacity-30" />
            <p className="text-sm">还没有 Mod</p>
            <p className="text-xs mt-1 opacity-60">去对话页让 Agent 帮你安装第一个 Mod</p>
          </div>
        )}
        {filtered.length === 0 && mods.length > 0 && (
          <div className="mods-empty-state mods-empty-search flex flex-col items-center justify-center py-20 text-surface-500">
            <Search size={32} className="mb-2 opacity-30" />
            <p className="text-sm">没有匹配的 Mod</p>
          </div>
        )}
      </div>

      {/* Bottom status bar */}
      <div className="flex items-center justify-between px-4 py-1.5 border-t border-surface-600 bg-surface-800 text-xs text-surface-500">
        <span>已选 {selected.size} 个</span>
        <span>共 {mods.length} 个 Mod · 占用 {totalSize > 1024 ? (totalSize / 1024).toFixed(1) + 'GB' : totalSize.toFixed(0) + 'MB'}</span>
        {selected.size > 0 && (
          <button onClick={previewBatchDelete} disabled={batchBusy} className="btn-ghost text-cyber-red flex items-center gap-1">
            {batchBusy ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />} 批量删除
          </button>
        )}
      </div>

      {/* 批量卸载统一预览：确认一次，逐个走后端真实卸载门与快照。 */}
      {batchDelete && (() => {
        const totalFiles = batchDelete.items.reduce((sum, item) => sum + (item.preview.will_delete_count || 0), 0)
        const workshopCount = batchDelete.items.filter(item => item.preview.will_unsubscribe).length
        const dependents = [...new Set(batchDelete.items.flatMap(item => item.preview.dependents || []))]
        return (
          <div className="fixed inset-0 bg-black/65 flex items-center justify-center z-50" onClick={() => setBatchDelete(null)}>
            <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-lg w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-cyber-red/10 flex items-center justify-center">
                  <AlertTriangle size={20} className="text-cyber-red" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">确认批量卸载</h3>
                  <p className="text-xs text-surface-500">共 {batchDelete.items.length} 个 Mod</p>
                </div>
              </div>
              <div className="bg-surface-900 rounded-md p-3 mb-4 text-xs text-surface-400 space-y-2">
                <p>将删除约 <span className="text-cyber-red">{totalFiles}</span> 个本地文件{workshopCount ? `，并退订 ${workshopCount} 个工坊项目` : ''}。</p>
                <div className="max-h-32 overflow-y-auto space-y-1 text-white/80">
                  {batchDelete.items.slice(0, 12).map(item => <p key={item.mod.id}>• {item.mod.name}</p>)}
                  {batchDelete.items.length > 12 && <p>…另有 {batchDelete.items.length - 12} 个</p>}
                </div>
                {!!dependents.length && <p className="text-cyber-yellow">⚠️ 受影响依赖：{dependents.slice(0, 8).join('、')}{dependents.length > 8 ? ' 等' : ''}</p>}
                <p className="text-surface-500">每个本地 Mod 卸载前仍会建立快照；单项失败会单独报告，不会伪装成全部成功。</p>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setBatchDelete(null)} className="btn-ghost">取消</button>
                <button onClick={confirmBatchDelete} className="tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors">确认全部卸载</button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Delete confirm dialog */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowDeleteConfirm(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-sm w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-cyber-red/10 flex items-center justify-center">
                <AlertTriangle size={20} className="text-cyber-red" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">确认卸载</h3>
                <p className="text-xs text-surface-500">{showDeleteConfirm.name}</p>
              </div>
            </div>
            <div className="bg-surface-900 rounded-md p-3 mb-4 text-xs text-surface-400 space-y-1.5">
              {showDeleteConfirm.preview?.will_unsubscribe ? (
                <p>工坊 Mod：将从 Steam <span className="text-cyber-yellow">退订</span>（Steam 托管文件不删除，退订后自动移除）。</p>
              ) : (
                <p>将删除 <span className="text-cyber-red">{showDeleteConfirm.preview?.will_delete_count ?? '?'}</span> 个 mod 文件。</p>
              )}
              {showDeleteConfirm.preview?.dependents?.length > 0 && (
                <p className="text-cyber-yellow">⚠️ {showDeleteConfirm.preview.dependents.join('、')} 依赖此 Mod，卸载可能导致它们失效。</p>
              )}
              <p className="text-surface-500">卸载前会自动建快照，此操作可回滚。</p>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowDeleteConfirm(null)} className="btn-ghost">取消</button>
              <button onClick={confirmDelete} className="tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors">删除</button>
            </div>
          </div>
        </div>
      )}

      {/* 依赖链启停门禁 */}
      {dependencyGate && (
        <div className="fixed inset-0 bg-black/65 flex items-center justify-center z-50" onClick={() => setDependencyGate(null)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-md w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${dependencyGate.data.blocked || !dependencyGate.enabling ? 'bg-cyber-red/10' : 'bg-cyber-cyan/10'}`}>
                <AlertTriangle size={20} className={dependencyGate.data.blocked || !dependencyGate.enabling ? 'text-cyber-red' : 'text-cyber-cyan'} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">
                  {dependencyGate.data.blocked ? '缺少前置依赖' : dependencyGate.enabling ? '确认启用依赖链' : '确认级联禁用'}
                </h3>
                <p className="text-xs text-surface-500">{dependencyGate.mod.name}</p>
              </div>
            </div>
            <div className="bg-surface-900 rounded-md p-3 mb-4 text-xs text-surface-400 space-y-2">
              <p>{dependencyGate.data.note}</p>
              {!!dependencyGate.data.dependents?.length && (
                <div>
                  <p className="text-cyber-yellow mb-1">依赖它、将被连带禁用：</p>
                  <p className="text-white/80">{dependencyGate.data.dependents.map(item => item.name || item.id).join(' → ')}</p>
                </div>
              )}
              {!!dependencyGate.data.dependencies?.length && (
                <div>
                  <p className="text-cyber-cyan mb-1">启用顺序（前置优先）：</p>
                  <p className="text-white/80">{dependencyGate.data.dependencies.map(item => item.name || item.id).join(' → ')}</p>
                </div>
              )}
              {!!dependencyGate.data.missing_dependencies?.length && (
                <div>
                  <p className="text-cyber-red mb-1">尚未安装：</p>
                  <p className="font-mono text-white/80">{dependencyGate.data.missing_dependencies.join('、')}</p>
                  <p className="text-surface-500 mt-2">如果等价前置已从 GitHub、工坊或本地装过，请到对话页让 Agent 核对后建立跨来源依赖映射。</p>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDependencyGate(null)} className="btn-ghost">
                {dependencyGate.data.blocked ? '知道了' : '取消'}
              </button>
              {!dependencyGate.data.blocked && (
                <button onClick={confirmDependencyToggle}
                  className={dependencyGate.enabling ? 'btn-cyber' : 'tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors'}>
                  {dependencyGate.enabling ? '启用依赖并继续' : '全部禁用'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 下载新 Mod 弹窗 */}
      {showDownload && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => !dlBusy && setShowDownload(false)}>
          <div className="bg-surface-800 border border-surface-600 rounded-lg p-6 max-w-md w-full shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3">
              <Download size={18} className="text-cyber-cyan" />
              <h3 className="text-sm font-semibold text-white">下载新 Mod</h3>
            </div>
            <p className="text-xs text-surface-500 mb-3">粘贴 GitHub / Thunderstore / GameBanana 的 mod 链接，自动下载并安装到当前游戏。Nexus 请去对话页用搜索。</p>
            <input autoFocus value={dlUrl} onChange={e => setDlUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') doDownload() }}
              placeholder="thunderstore.io/c/.../p/.../  或  github.com/owner/repo"
              className="input-cyber mb-4" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowDownload(false)} className="btn-ghost" disabled={dlBusy}>取消</button>
              <button onClick={doDownload} disabled={dlBusy || !dlUrl.trim()} className="btn-cyber flex items-center gap-1.5">
                {dlBusy ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />} 下载并安装
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
