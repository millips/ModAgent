import React, { useState, useEffect, useRef } from 'react'
import { Search, Download, CheckSquare, Trash2, RefreshCw, AlertTriangle, Archive, RotateCcw, XCircle, FolderInput, Link2, Sparkles, Share2, Layers, ChevronDown, ChevronRight } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { isPAccessEnabled, usePLicenseStatus } from '../license/pLicense'
import { usePShareProfile } from '../pshare/pShareStore'
import ShareExportDialog from './ShareExportDialog'
import { tr } from '../i18n'
import { uninstallOutcome } from './uninstallOutcome.mjs'

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

const FILTERS = [
  { value: 'all', key: 'all' },
  { value: 'updates', key: 'updates' },
  { value: 'disabled', key: 'disabled' },
]

export default function ModsPage({ toast, api, onRefresh, refreshKey, status, language = 'zh-CN' }) {
  const t = key => tr(language, key)
  const pLicense = usePLicenseStatus()
  const pShareProfile = usePShareProfile()
  const canCreateShare = isPAccessEnabled(pLicense) && Boolean(pShareProfile)
  const canEnrollShare = isPAccessEnabled(pLicense) && !pShareProfile
  const [mods, setMods] = useState([])
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('全部')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selected, setSelected] = useState(new Set())
  const [hovered, setHovered] = useState(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(null)
  const [dependencyGate, setDependencyGate] = useState(null)
  const [batchDelete, setBatchDelete] = useState(null)
  const [batchBusy, setBatchBusy] = useState(false)
  const [batchProgress, setBatchProgress] = useState(null)
  const [actionLock, setActionLock] = useState(null)
  const [showDownload, setShowDownload] = useState(false)
  const [dlUrl, setDlUrl] = useState('')
  const [dlBusy, setDlBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [updateProgress, setUpdateProgress] = useState(null)
  const [updateReview, setUpdateReview] = useState(null)
  const [updateSelected, setUpdateSelected] = useState(new Set())
  const [updatingSelected, setUpdatingSelected] = useState(false)
  const [binding, setBinding] = useState(false)
  const [bindingProgress, setBindingProgress] = useState(null)
  const [alignmentReview, setAlignmentReview] = useState(null)
  const [manualSource, setManualSource] = useState({})
  const [manualSourcePreview, setManualSourcePreview] = useState({})
  const [enriching, setEnriching] = useState(false)
  const [showShareExport, setShowShareExport] = useState(false)
  const [expandedPackages, setExpandedPackages] = useState(new Set())
  const [packageMerge, setPackageMerge] = useState(null)
  const [packageMerging, setPackageMerging] = useState(false)
  const bindingAbortRef = useRef(null)
  const updateAbortRef = useRef(null)

  useEffect(() => { loadFromApi() }, [refreshKey, status?.game_slug, status?.game_instance_id])

  const loadFromApi = async () => {
    try {
      const scope = status?.game_instance_id || status?.game_slug || ''
      const r = await fetch(scope ? `${api}/mods?game_slug=${encodeURIComponent(scope)}` : `${api}/mods`)
      if (!r.ok) throw new Error(`mods request failed: ${r.status}`)
      const apiMods = await r.json()
      if (!Array.isArray(apiMods)) throw new Error('mods response is not an array')
      const mapped = apiMods.map(m => ({
        id: m.id || '', name: m.name || m.id, name_cn: m.localized_name || '', version: m.version || '?',
        latest: null, category: m.source || '本地', desc: m.summary || '功能简介尚未生成',
        summaryEvidence: m.summary_evidence || '',
        summaryConfidence: m.summary_confidence || '',
        sourceUrl: m.source_url || '',
        sourceKey: m.source_key || '',
        sourceMatchMethod: m.source_match_method || '',
        sourceConfidence: Number(m.source_confidence) || 0,
        installedBy: m.installed_by || '',
        managementProvider: m.management_provider || 'local_files',
        dependencies: Array.isArray(m.dependencies) ? m.dependencies : [],
        fileCount: Number(m.file_count) || 0,
        variantCount: Number(m.variant_count) || 0,
        variants: Array.isArray(m.variants) ? m.variants : [],
        managementUnit: m.management_unit || 'package',
        hasVerifiedSource: Boolean(m.source_key && m.source_url),
        size: '',
        hasConflict: false, disabled: !!m.disabled,
      }))
      setMods(mapped)
      if (mapped.some(mod => !mod.name_cn || !mod.summaryEvidence)) {
        void enrichCatalog(scope)
      }
    } catch (_) { toast('加载 Mod 列表失败', 'error') }
  }

  const enrichCatalog = async (scope = '', force = false) => {
    if (enriching) return
    setEnriching(true)
    try {
      const query = new URLSearchParams()
      if (scope) query.set('game_slug', scope)
      if (force) query.set('force', 'true')
      const response = await fetch(`${api}/mods/enrich?${query.toString()}`, { method: 'POST' })
      if (!response.ok) throw new Error(`enrichment request failed: ${response.status}`)
      const result = await response.json()
      const notes = result.notes || {}
      setMods(previous => previous.map(mod => {
        const note = notes[String(mod.id)]
        if (!note) return mod
        return {
          ...mod,
          name_cn: note.localized_name || mod.name_cn,
          desc: note.summary || mod.desc,
          summaryEvidence: note.evidence_kind || mod.summaryEvidence,
          summaryConfidence: note.confidence || mod.summaryConfidence,
        }
      }))
      if (force) {
        if (result.status === 'llm_required') toast('请先在设置中配置大模型 API', 'error')
        else if (result.status === 'generation_failed') toast('AI 功能简介生成失败，可稍后重试', 'error')
        else toast(result.updated ? `已更新 ${result.updated} 个 Mod 的中文简介` : '中文简介缓存已是最新')
      }
    } catch (_) {
      if (force) toast('AI 功能简介生成失败，可稍后重试', 'error')
    } finally {
      setEnriching(false)
    }
  }

  const reconcileMods = async () => {
    toast('对账并同步中...')
    try {
      const scope = status?.game_instance_id || status?.game_slug || ''
      const r = await fetch(`${api}/mods/reconcile?game_slug=${encodeURIComponent(scope)}&sync_missing=true`, { method: 'POST' })
      const d = await r.json()
      const merged = Number(d.duplicates_merged) || 0
      const removed = Number(d.removed_missing?.length) || 0
      if (d.issues?.length) {
        const names = d.issues.slice(0, 3).map(i => `${i.name}(${i.problem})`).join('、')
        emitFeedback('warning', { source: 'mod-reconcile', count: d.issues.length })
        toast(`${removed ? `已从管理清单同步移除 ${removed} 个已被手动删空的 Mod；` : ''}${merged ? `已合并 ${merged} 条重复记录；` : ''}发现 ${d.issues.length}/${d.checked} 个 Mod 账实不符: ${names}${d.issues.length > 3 ? ' 等' : ''}`, 'error')
      } else {
        emitFeedback('notice', { source: 'mod-reconcile', count: merged })
        toast(merged
          ? `对账完成：已安全合并 ${merged} 条重复记录，${d.checked} 个 Mod 账实一致`
          : `对账完成：${removed ? `已同步移除 ${removed} 个已手动删除的 Mod；` : ''}${d.checked} 个 Mod 账实一致`)
      }
      if (merged || removed) await loadFromApi()
    } catch (_) { emitFeedback('error', { source: 'mod-reconcile' }); toast('对账失败', 'error') }
  }

  const cancelLongTask = async (taskKind) => {
    try {
      const response = await fetch(`${api}/tasks/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_kind: taskKind }),
      })
      const result = await response.json()
      if (result.ok) {
        toast('已请求取消；当前网络请求结束后会安全停止')
        emitFeedback('cancel', { source: taskKind })
      }
      if (taskKind === 'source_align') bindingAbortRef.current?.abort()
      if (taskKind === 'update_check') updateAbortRef.current?.abort()
    } catch (_) {
      toast('取消请求发送失败', 'error')
    }
  }

  // 检查更新：显示逐项进度，完成后由用户勾选要更新的项目。
  const checkUpdates = async () => {
    if (checking) {
      await cancelLongTask('update_check')
      return
    }
    setChecking(true)
    setUpdateProgress({ completed: 0, total: mods.length, current: '' })
    toast('检查更新中...')
    const controller = new AbortController()
    updateAbortRef.current = controller
    let pollTimer = null
    const pollProgress = async () => {
      try {
        const response = await fetch(`${api}/downloads/status`)
        const state = await response.json()
        if (state.task_kind !== 'update_check') return
        setUpdateProgress({
          completed: Number(state.completed_count) || 0,
          total: Number(state.total_count) || mods.length,
          current: state.current_item?.name || '',
        })
      } catch (_) {}
    }
    try {
      pollTimer = window.setInterval(pollProgress, 400)
      const r = await fetch(api + '/tool/mod_update_check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
        signal: controller.signal,
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) throw new Error(data.error)
      if (data.cancelled) {
        toast('检查更新已取消；已完成的来源绑定会保留')
        return
      }
      const ups = data.updates_available || []
      const map = {}
      ups.forEach(u => { map[String(u.mod_id)] = u.latest })
      setMods(prev => prev.map(m => ({ ...m, latest: map[String(m.id)] || null })))
      setUpdateProgress({
        completed: Number(data.summary?.total) || mods.length,
        total: Number(data.summary?.total) || mods.length,
        current: '',
      })
      setUpdateReview(ups.length
        ? { updates: ups, summary: data.summary || {}, items: data.items || [] }
        : null)
      setUpdateSelected(new Set(ups.map(item => String(item.mod_id))))
      emitFeedback('notice', { source: 'update-check', count: ups.length })
      const failed = data.failed_checks?.length || 0
      const checked = (data.checked_nexus || 0) + (data.checked_thunderstore || 0)
      if (failed) toast(`检查完成：${checked} 个成功，${failed} 个暂时无法查询${ups.length ? `，发现 ${ups.length} 个更新` : ''}`, 'error')
      else toast(ups.length ? `检测到 ${ups.length} 个可更新项目，请勾选后执行` : `检查完成：${checked} 个已绑定 Mod 均为最新`)
    } catch (error) {
      if (error?.name === 'AbortError') {
        toast('检查更新已取消')
        return
      }
      emitFeedback('error', { source: 'update-check' })
      toast(error?.message || '检查更新失败', 'error')
    } finally {
      if (pollTimer) window.clearInterval(pollTimer)
      updateAbortRef.current = null
      setChecking(false)
      setUpdateProgress(null)
    }
  }

  const runSelectedUpdates = async () => {
    const targets = (updateReview?.updates || []).filter(
      item => updateSelected.has(String(item.mod_id))
    )
    if (!targets.length || updatingSelected) return
    setUpdatingSelected(true)
    const succeeded = []
    const failed = []
    for (const item of targets) {
      try {
        const response = await fetch(api + '/tool/mod_update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: String(item.mod_id) }),
        })
        const envelope = await response.json()
        const result = JSON.parse(envelope.result || '{}')
        if (result.error) throw new Error(result.error)
        succeeded.push(item.name)
      } catch (error) {
        failed.push({ name: item.name, error: error?.message || '更新失败' })
      }
    }
    setUpdatingSelected(false)
    setUpdateReview(null)
    setUpdateSelected(new Set())
    await loadFromApi()
    onRefresh?.()
    if (failed.length) {
      toast(`更新完成：成功 ${succeeded.length}，失败 ${failed.length}（${failed.slice(0, 3).map(item => item.name).join('、')}）`, 'error')
    } else {
      toast(`已更新 ${succeeded.length} 个 Mod`)
    }
  }

  const runAlignment = async (targetMods = null, forceRebind = false) => {
    const targets = Array.isArray(targetMods)
      ? targetMods
      : mods.filter(mod => !mod.hasVerifiedSource)
    if (!targets.length) {
      toast('全部 Mod 都已有维护来源，无需重复绑定')
      return
    }
    setBinding(true)
    setBindingProgress({ completed: 0, total: targets.length, current: '' })
    const controller = new AbortController()
    bindingAbortRef.current = controller
    toast(targetMods
      ? `正在单独对齐 ${targets[0]?.name || '该 Mod'}…`
      : `正在对齐 ${targets.length} 个尚未绑定的 Mod…`)
    let pollTimer = null
    const pollProgress = async () => {
      try {
        const response = await fetch(`${api}/downloads/status`)
        const state = await response.json()
        if (state.task_kind !== 'source_align') return
        setBindingProgress({
          completed: Number(state.completed_count) || 0,
          total: Number(state.total_count) || targets.length,
          current: state.current_item?.name || '',
        })
      } catch (_) {}
    }
    try {
      pollTimer = window.setInterval(pollProgress, 400)
      const response = await fetch(api + '/tool/mod_source_align', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          force_refresh: false,
          force_rebind: forceRebind,
          mod_ids: targetMods ? targets.map(mod => String(mod.id)) : [],
        }),
        signal: controller.signal,
      })
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error) throw new Error(result.error)
      if (result.cancelled) {
        toast('来源对齐已取消；此前成功绑定的项目已保留')
        return
      }
      const summary = result.summary || {}
      const attempted = Number(result.attempted) || targets.length
      setBindingProgress({ completed: attempted, total: attempted, current: '' })
      emitFeedback('notice', { source: 'source-align', count: summary.bound || 0 })
      const ambiguous = result.ambiguous || []
      const unmatched = result.unmatched || []
      if (ambiguous.length || unmatched.length) {
        setAlignmentReview({
          items: ambiguous,
          unmatched,
        })
        setManualSource({})
        setManualSourcePreview({})
      }
      toast(`对齐完成：沿用已有 ${summary.already_bound || 0}，新增 ${summary.bound || 0}，待确认 ${summary.ambiguous || 0}，未匹配 ${summary.unmatched || 0}`)
      await loadFromApi()
      onRefresh?.()
    } catch (error) {
      if (error?.name === 'AbortError') {
        toast('来源对齐已取消；此前成功绑定的项目已保留')
        return
      }
      emitFeedback('error', { source: 'source-align' })
      toast(error?.message || '来源绑定失败，已保留此前完成的绑定', 'error')
    } finally {
      if (pollTimer) window.clearInterval(pollTimer)
      bindingAbortRef.current = null
      setBinding(false)
      // 对齐结果已通过 toast / 歧义面板交代；不要让右下角“已结束”进度卡再滞留。
      setBindingProgress(null)
    }
  }

  const bindRecognized = () => (
    binding ? cancelLongTask('source_align') : runAlignment()
  )

  const confirmAlignmentCandidate = async (item, candidate) => {
    const lockId = `align:${item.mod_id}`
    if (actionLock) return
    setActionLock(lockId)
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 30000)
    try {
      const body = {
        local_mod_id: String(item.mod_id),
        source: candidate.source,
        source_key: String(candidate.source_key || ''),
        source_url: candidate.url || '',
        candidate_name: candidate.name || '',
        latest_version: candidate.latest_version || candidate.version || '',
        confirmed: true,
      }
      if (candidate.source === 'nexus') body.nexus_mod_id = Number(candidate.source_key)
      const response = await fetch(api + '/tool/mod_source_bind', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`来源绑定请求失败 (${response.status})`)
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error || !result.bound) throw new Error(result.error || '绑定失败')
      const remainingItems = (alignmentReview?.items || []).filter(
        row => String(row.mod_id) !== String(item.mod_id),
      )
      const remainingUnmatched = (alignmentReview?.unmatched || []).filter(
        row => String(row.mod_id) !== String(item.mod_id),
      )
      setAlignmentReview(remainingItems.length || remainingUnmatched.length
        ? { ...alignmentReview, items: remainingItems, unmatched: remainingUnmatched }
        : null)
      setManualSourcePreview(previous => {
        const next = { ...previous }
        delete next[item.mod_id]
        return next
      })
      toast(`${item.name} 已确认绑定到 ${candidate.name || candidate.source_key}`)
      await loadFromApi()
      onRefresh?.()
    } catch (error) {
      const message = error?.name === 'AbortError'
        ? '来源确认超过 30 秒，已停止等待；此前确认项不会丢失，请稍后重试'
        : (error?.message || '确认绑定失败')
      toast(message, 'error')
    } finally {
      window.clearTimeout(timeoutId)
      setActionLock(null)
    }
  }

  const parseManualSourceUrl = (rawUrl) => {
    let url
    try { url = new URL(String(rawUrl || '').trim()) } catch (_) { return null }
    const host = url.hostname.toLowerCase()
    const path = url.pathname
    const nexus = path.match(/\/mods\/(\d+)/i)
    if (host.endsWith('nexusmods.com') && nexus) {
      return { source: 'nexus', source_key: nexus[1], source_url: url.href }
    }
    const thunder = path.match(/\/c\/[^/]+\/p\/([^/]+)\/([^/?#]+)/i)
    if (host.endsWith('thunderstore.io') && thunder) {
      return {
        source: 'thunderstore',
        source_key: `${decodeURIComponent(thunder[1])}-${decodeURIComponent(thunder[2])}`,
        source_url: url.href,
      }
    }
    return null
  }

  const inspectManualSource = async (item) => {
    const rawUrl = String(manualSource[item.mod_id] || '').trim()
    const parsed = parseManualSourceUrl(rawUrl)
    if (!parsed) {
      toast('请粘贴 Nexus 或 Thunderstore 的具体 Mod 维护页网址', 'error')
      return
    }
    const lockId = `manual-source:${item.mod_id}`
    if (actionLock) return
    setActionLock(lockId)
    try {
      const response = await fetch(api + '/tool/mod_source_bind', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          local_mod_id: String(item.mod_id),
          ...parsed,
          nexus_mod_id: parsed.source === 'nexus' ? Number(parsed.source_key) : undefined,
          confirmed: false,
        }),
      })
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error || !result.requires_confirmation) {
        throw new Error(result.error || '网址未能通过来源核验')
      }
      setManualSourcePreview(previous => ({ ...previous, [item.mod_id]: {
        ...parsed, preview: result.preview || {},
      }}))
      toast('网址已核验，请确认是否绑定到当前 Mod')
    } catch (error) {
      toast(error?.message || '网址核验失败', 'error')
    } finally {
      setActionLock(null)
    }
  }

  const confirmManualSource = async (item) => {
    const candidate = manualSourcePreview[item.mod_id]
    if (!candidate) return
    await confirmAlignmentCandidate(item, {
      source: candidate.source,
      source_key: candidate.source_key,
      url: candidate.source_url,
      name: candidate.preview?.nexus?.name || candidate.preview?.source?.name || candidate.source_key,
      latest_version: candidate.preview?.nexus?.version || candidate.preview?.source?.version || '',
    })
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
    if (
      search
      && !m.name.toLowerCase().includes(search.toLowerCase())
      && !m.name_cn.includes(search)
      && !m.desc.toLowerCase().includes(search.toLowerCase())
    ) return false
    if (catFilter !== '全部' && m.category !== catFilter) return false
    if (statusFilter === 'updates' && !m.latest) return false
    if (statusFilter === '有冲突' && !m.hasConflict) return false
    if (statusFilter === 'disabled' && !m.disabled) return false
    return true
  })

  const toggleSelect = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const togglePackageExpanded = (id) => {
    setExpandedPackages(previous => {
      const next = new Set(previous)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const beginPackageMerge = () => {
    const chosen = mods.filter(mod => selected.has(mod.id))
    if (chosen.length < 2) return
    const first = chosen[0]?.name_cn || chosen[0]?.name || '自定义 Mod 包'
    setPackageMerge({ name: first, items: chosen })
  }

  const confirmPackageMerge = async () => {
    if (!packageMerge || packageMerging) return
    const name = String(packageMerge.name || '').trim()
    if (!name) {
      toast('请为合并后的 Mod 包填写名称', 'error')
      return
    }
    setPackageMerging(true)
    try {
      const scope = status?.game_instance_id || status?.game_slug || ''
      const response = await fetch(`${api}/mods/package-merge`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mod_ids: packageMerge.items.map(item => item.id),
          package_name: name,
          game_slug: scope,
        }),
      })
      const result = await response.json()
      if (!response.ok || !result.ok) throw new Error(result.detail || result.error || 'package_merge_failed')
      setSelected(new Set())
      setPackageMerge(null)
      await loadFromApi()
      onRefresh?.()
      toast(`已合并为“${result.name}”：${result.file_count} 个文件；未改动游戏文件`)
    } catch (error) {
      toast('合并记录失败：' + (error?.message || '请稍后重试'), 'error')
    } finally {
      setPackageMerging(false)
    }
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
      if (!r.ok || preview.error || preview.requires_confirmation !== true) throw new Error(preview.error || '无法取得卸载预览')
      setShowDeleteConfirm({ ...mod, preview })
    } catch (e) {
      setShowDeleteConfirm(null)
      toast(friendlyErr(e?.message || '卸载预览失败，未执行删除'), 'error')
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
      const outcome = uninstallOutcome(data, language)
      if (!r.ok || !outcome.complete) {
        emitFeedback('error', { source: 'uninstall' })
        toast(outcome.message, 'error')
        loadFromApi()
        onRefresh?.()
      }
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

  const toggleMod = async (mod, confirmed = false, confirmationToken = '') => {
    const enabling = !!mod.disabled
    const action = enabling ? 'mod_enable' : 'mod_disable'
    setActionLock(mod.id)
    if (!confirmed) toast(`${enabling ? '检查启用条件' : '检查依赖影响'}：${mod.name}...`)
    try {
      const r = await fetch(api + '/tool/' + action, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mod_id: mod.id,
          ...(confirmed ? { confirmed: true, confirmation_token: confirmationToken } : {}),
        })
      })
      const d = await r.json()
      const data = JSON.parse(d.result || '{}')
      if (data.error) {
        emitFeedback('error', { source: action })
        toast(friendlyErr(data.error), 'error')
      } else if (data.blocked || data.requires_confirmation || data.requires_external_manager) {
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
    await toggleMod(gate.mod, true, gate.data.confirmation_token || '')
  }

  const previewBatchDelete = async () => {
    const targets = mods.filter(mod => selected.has(mod.id))
    if (!targets.length || batchBusy) return
    setBatchBusy(true)
    setBatchProgress({ phase: 'preview', completed: 0, total: targets.length, current: '' })
    toast(`正在核对 ${targets.length} 个 Mod 的卸载影响...`)
    try {
      const items = []
      for (let index = 0; index < targets.length; index += 1) {
        const mod = targets[index]
        setBatchProgress({ phase: 'preview', completed: index, total: targets.length, current: mod.name })
        const r = await fetch(api + '/tool/mod_uninstall', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: mod.id }),
        })
        const d = await r.json()
        const preview = JSON.parse(d.result || '{}')
        if (!r.ok || preview.error || preview.requires_confirmation !== true) throw new Error(preview.error || `无法预览 ${mod.name}`)
        items.push({ mod, preview })
        setBatchProgress({ phase: 'preview', completed: index + 1, total: targets.length, current: mod.name })
      }
      setBatchDelete({ items })
      emitFeedback('warning', { source: 'batch-uninstall-preview', count: items.length })
    } catch (error) {
      emitFeedback('error', { source: 'batch-uninstall-preview' })
      toast(friendlyErr(error?.message || '批量卸载预览失败'), 'error')
    } finally {
      setBatchBusy(false)
      setBatchProgress(null)
    }
  }

  const confirmBatchDelete = async () => {
    const plan = batchDelete
    if (!plan || batchBusy) return
    setBatchDelete(null)
    setBatchBusy(true)
    const succeeded = []
    const failed = []
    let snapshotId = ''
    try {
      setBatchProgress({ phase: 'snapshot', completed: 0, total: plan.items.length, current: '正在创建批量删除前安全快照' })
      const snapshotResponse = await fetch(api + '/tool/snapshot_create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trigger_mod_name: `批量删除 ${plan.items.length} 个 Mod 前` }),
      })
      const snapshotEnvelope = await snapshotResponse.json()
      const snapshotData = JSON.parse(snapshotEnvelope.result || '{}')
      if (snapshotData.error || !snapshotData.snapshot_id) throw new Error(snapshotData.error || '无法创建批量删除前安全快照')
      snapshotId = snapshotData.snapshot_id
    } catch (error) {
      setBatchBusy(false)
      setBatchProgress(null)
      emitFeedback('error', { source: 'batch-uninstall-snapshot' })
      toast(friendlyErr(error?.message || '无法创建批量删除前安全快照，已取消删除'), 'error')
      return
    }
    for (let index = 0; index < plan.items.length; index += 1) {
      const item = plan.items[index]
      setBatchProgress({ phase: 'delete', completed: index, total: plan.items.length, current: item.mod.name, succeeded: succeeded.length, failed: failed.length })
      try {
        const r = await fetch(api + '/tool/mod_uninstall', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mod_id: item.mod.id, confirmed: true, snapshot_id: snapshotId }),
        })
        const d = await r.json()
        const data = JSON.parse(d.result || '{}')
        if (!r.ok || !uninstallOutcome(data, language).complete) failed.push(item.mod.name)
        else succeeded.push(item.mod.id)
      } catch (_) {
        failed.push(item.mod.name)
      }
      setBatchProgress({ phase: 'delete', completed: index + 1, total: plan.items.length, current: item.mod.name, succeeded: succeeded.length, failed: failed.length })
    }
    if (succeeded.length) {
      emitFeedback('remove-complete', { source: 'batch-uninstall', count: succeeded.length })
      setSelected(prev => new Set([...prev].filter(id => !succeeded.includes(id))))
    }
    // A partial removal may change files without removing its management row.
    // Refresh for every outcome, while leaving failed targets selected.
    await loadFromApi()
    onRefresh?.()
    if (failed.length) {
      emitFeedback('error', { source: 'batch-uninstall', count: failed.length })
      toast(`已卸载 ${succeeded.length} 个；${failed.length} 个失败：${failed.slice(0, 3).join('、')}`, 'error')
    } else {
      toast(`已卸载 ${succeeded.length} 个 Mod`)
    }
    setBatchBusy(false)
    setBatchProgress(null)
  }

  const totalSize = mods.reduce((sum, m) => {
    const num = parseFloat(m.size)
    const unit = m.size.includes('GB') ? 1024 : m.size.includes('MB') ? 1 : 0.001
    return sum + num * unit
  }, 0)
  const boundCount = mods.filter(mod => mod.hasVerifiedSource).length
  const unboundCount = Math.max(0, mods.length - boundCount)
  const selectedMods = mods.filter(mod => selected.has(mod.id))
  const selectedUnalignedCount = selectedMods.filter(mod => !mod.hasVerifiedSource).length
  // 分享包会把来源链接交给接收者；任何一个来源不明的条目都不能混入。
  // 因此入口只在「所选全部已对齐」时出现，而不是等导出时才给用户一个失败提示。
  const canExportSelectedShare = canCreateShare
    && selectedMods.length > 0
    && selectedMods.every(mod => mod.hasVerifiedSource)

  const openSourcePage = async mod => {
    if (!mod?.hasVerifiedSource || !mod.sourceUrl) return
    const result = await window.modagent?.openExternal?.(mod.sourceUrl)
    if (!result?.ok) toast('无法打开已对齐的原始发布页', 'error')
  }

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Top toolbar */}
      <div className="p-3 border-b border-surface-600 bg-surface-800 space-y-2">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-500" />
            <input
              className="input-cyber pl-9"
              placeholder={t('searchMods')}
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={`px-3 py-1.5 rounded-md text-xs transition-all ${statusFilter === f.value ? 'bg-cyber-blue/20 text-cyber-cyan border border-cyber-cyan/30' : 'text-surface-500 hover:text-white'}`}
              >
                {t(f.key)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap justify-end gap-1 ml-auto">
            <button className="btn-ghost flex items-center gap-1" onClick={reconcileMods}
              title="校验每个已装 mod 记录的文件是否还在磁盘上,揪出空账/缺文件">
              {t('reconcile')}
            </button>
            <button
              className={`btn-ghost flex items-center gap-1 ${checking ? 'text-cyber-red' : ''}`}
              onClick={checkUpdates}
              disabled={binding}
              title={checking ? '取消本轮更新检查' : '逐项检查版本，完成后勾选需要更新的项目'}
            >
              {checking ? <XCircle size={14} /> : <RefreshCw size={14} />}
              {checking
                ? `取消检查 ${updateProgress?.completed || 0}/${updateProgress?.total || mods.length}`
                : t('checkUpdates')}
            </button>
            <button
              className={`btn-ghost flex items-center gap-1 ${binding ? 'text-cyber-red' : ''}`}
              onClick={bindRecognized}
              disabled={checking || (!binding && !unboundCount)}
              title={unboundCount
                ? `仅处理 ${unboundCount} 个尚未完成来源核验的项；已有 ${boundCount} 个不会重复查询`
                : '全部 Mod 都已有维护来源'}>
              {binding ? <XCircle size={14} /> : <Link2 size={14} />}
              {binding
                ? `取消对齐 ${bindingProgress?.completed || 0}/${bindingProgress?.total || mods.length}`
                : `${t('align')} ${boundCount}/${mods.length}`}
            </button>
            <button
              className="btn-ghost flex items-center gap-1"
              onClick={() => enrichCatalog(status?.game_instance_id || status?.game_slug || '', true)}
              disabled={enriching}
              title="依据本地清单和已绑定来源生成中文名称与一句话功能简介；证据不足时会明确标记为 AI 推测"
            >
              <Sparkles size={14} className={enriching ? 'animate-pulse' : ''} />
              {enriching ? t('generatingSummary') : t('enrichSummary')}
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={loadFromApi}>
              {t('refreshMods')}
            </button>
            <button className="btn-cyber flex items-center gap-1.5" onClick={() => setShowDownload(true)}>
              <Download size={14} /> {t('downloadNewMod')}
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
              <FolderInput size={14} /> {t('dropFolder')}
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
              <FolderInput size={14} /> {t('modFolder')}
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
              <FolderInput size={14} /> {t('toolsFolder')}
            </button>
            <button className="btn-ghost flex items-center gap-1" onClick={toggleAll}>
              <CheckSquare size={14} /> {selected.size === filtered.length ? t('clearSelection') : t('selectAll')}
            </button>
          </div>
        </div>
        {bindingProgress && (
          <div className="rounded-md border border-cyber-cyan/20 bg-surface-900/60 px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-3 text-[11px]">
              <span className="truncate text-surface-300">
                {binding
                  ? `正在绑定维护来源${bindingProgress.current ? `：${bindingProgress.current}` : ''}`
                  : '来源绑定完成'}
              </span>
              <span className="shrink-0 font-mono text-cyber-cyan">
                {bindingProgress.completed}/{bindingProgress.total}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-700">
              <div
                className="h-full rounded-full bg-cyber-cyan transition-all duration-300"
                style={{
                  width: `${bindingProgress.total
                    ? Math.min(100, (bindingProgress.completed / bindingProgress.total) * 100)
                    : 0}%`,
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Mod list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map((mod, i) => (
          <React.Fragment key={mod.id}>
          <div
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
                {mod.name_cn && mod.name_cn !== mod.name && (
                  <span className="text-xs text-surface-500 truncate">{mod.name}</span>
                )}
                <span className={`text-xs ${mod.disabled ? 'text-surface-500' : 'text-cyber-cyan/70'} font-mono`}>v{mod.version}</span>
                {mod.latest && !mod.disabled && (
                  <span className="relative flex items-center gap-1 text-xs text-cyber-orange">
                    <span className="w-2 h-2 rounded-full bg-cyber-orange shadow-[0_0_4px_#db6d28]"></span>
                    v{mod.latest}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[11px] text-surface-400">{mod.desc}</span>
                {mod.summaryEvidence && (
                  <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] ${
                    mod.summaryConfidence === 'low'
                      ? 'border-cyber-yellow/30 text-cyber-yellow'
                      : 'border-cyber-cyan/25 text-cyber-cyan'
                  }`}>
                    {mod.summaryEvidence === 'local_manifest'
                      ? '本地清单'
                      : mod.summaryEvidence === 'source_metadata'
                        ? '来源资料'
                        : 'AI 推测 · 待核验'}
                  </span>
                )}
                {mod.variantCount > 1 && (
                  <button
                    type="button"
                    onClick={() => togglePackageExpanded(mod.id)}
                    className="flex shrink-0 items-center gap-1 rounded border border-cyber-cyan/25 px-1.5 py-0.5 text-[9px] text-cyber-cyan hover:bg-cyber-cyan/10"
                    title={`该下载包包含 ${mod.variantCount} 个文件变体；更新、启用、禁用和卸载均按整包处理`}
                  >
                    {expandedPackages.has(mod.id) ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    包内 {mod.variantCount} 个变体
                  </button>
                )}
              </div>
            </div>

            {/* Tags */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span
                className="badge-cyan text-[10px]"
                title={mod.hasVerifiedSource
                  ? `维护来源：${mod.category}`
                  : `安装渠道：${mod.category}。尚未完成维护来源对齐，不能用于分享或自动更新。`}
              >{mod.category}</span>
              {!mod.hasVerifiedSource && (
                <span className="text-[9px] text-cyber-yellow" title="这是安装渠道，不等于已核验的原始发布来源">待对齐</span>
              )}
              {mod.hasVerifiedSource && (
                <button
                  type="button"
                  onClick={() => openSourcePage(mod)}
                  className="rounded-full border border-cyber-cyan/30 bg-cyber-cyan/10 px-2 py-0.5 text-[10px] text-cyber-cyan hover:bg-cyber-cyan/20"
                  title="打开已对齐的原始发布页；不会搜索或猜测未验证来源"
                >
                  ↗ 原始页
                </button>
              )}
              <span className="text-[10px] text-surface-500">{mod.size}</span>
            </div>

            {/* Actions - show on hover */}
            <div className={`flex items-center gap-1 shrink-0 transition-opacity duration-75 ${hovered === mod.id || mod.disabled || !mod.hasVerifiedSource ? 'opacity-100' : 'opacity-0'}`}>
              {!mod.hasVerifiedSource && (
                <button
                  disabled={binding || actionLock === `align:${mod.id}`}
                  onClick={() => runAlignment([mod])}
                  className="btn-ghost px-2 py-1.5 flex items-center gap-1 text-cyber-yellow"
                  title="单独对齐这个 Mod 的维护来源"
                >
                  <Link2 size={13} />
                  <span className="text-xs">+ 对齐</span>
                </button>
              )}
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
          {mod.variantCount > 1 && expandedPackages.has(mod.id) && (
            <div className="border-b border-cyber-cyan/15 bg-surface-900/55 px-16 py-2 text-xs">
              <div className="mb-1.5 flex items-center gap-2 text-cyber-cyan">
                <Layers size={12} />
                <span>包内变体（可查看；整包启停和卸载仍由主条目统一处理）</span>
              </div>
              <div className="grid gap-1 md:grid-cols-2 xl:grid-cols-3">
                {mod.variants.map(variant => (
                  <div key={variant.key} className="flex items-center justify-between gap-2 rounded border border-surface-700 bg-surface-800/60 px-2 py-1">
                    <span className="truncate text-surface-300" title={variant.name}>{variant.name}</span>
                    <span className={variant.disabled ? 'shrink-0 text-surface-500' : 'shrink-0 text-cyber-cyan/80'}>
                      {variant.disabled ? '已停用' : `${variant.file_count} 文件`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          </React.Fragment>
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
          <div className="flex items-center gap-2">
            {canExportSelectedShare && (
              <button onClick={() => setShowShareExport(true)} disabled={batchBusy} className="btn-ghost text-cyber-cyan flex items-center gap-1" title="P 创作者功能：把已选 Mod 导出为待审核的分享投稿包">
                <Share2 size={12} /> 导出分享配置
              </button>
            )}
            {canCreateShare && selectedUnalignedCount > 0 && (
              <span
                className="text-[10px] text-cyber-yellow"
                title="未对齐项没有可复核的原始发布链接，不能纳入分享包。请逐项点击“对齐”并确认候选来源。"
              >
                {selectedUnalignedCount} 个来源待对齐后才能分享
              </span>
            )}
            {canEnrollShare && <span className="text-[10px] text-surface-400">请先在设置中开通 P Share 创作者计划</span>}
            {selected.size >= 2 && (
              <button
                onClick={beginPackageMerge}
                disabled={batchBusy}
                className="btn-ghost text-cyber-cyan flex items-center gap-1"
                title="只合并 ModAgent 的本地管理记录，不移动、删除或改名游戏文件"
              >
                <Layers size={12} /> 合并为 Mod 包
              </button>
            )}
            <button onClick={previewBatchDelete} disabled={batchBusy} className="btn-ghost text-cyber-red flex items-center gap-1">
              {batchBusy ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />}
              {batchBusy && batchProgress
                ? `${batchProgress.phase === 'preview' ? '核对' : batchProgress.phase === 'snapshot' ? '创建快照' : '删除'} ${batchProgress.completed}/${batchProgress.total}`
                : '批量删除'}
            </button>
          </div>
        )}
      </div>

      {showShareExport && (
        <ShareExportDialog
          api={api}
          mods={selectedMods}
          toast={toast}
          language={language}
          gameName={status?.game || ''}
          gameSlug={status?.game_instance_id || status?.game_slug || ''}
          onClose={() => setShowShareExport(false)}
        />
      )}

      {packageMerge && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={() => !packageMerging && setPackageMerge(null)}>
          <div className="w-[min(92vw,620px)] rounded-lg border border-cyber-cyan/35 bg-surface-800 p-5 shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-semibold text-white">合并为一个 Mod 包</h3>
                <p className="mt-1 text-xs text-surface-400">把选中的 {packageMerge.items.length} 条本地管理记录合成一个父条目。不会移动、删除或改名任何游戏文件。</p>
              </div>
              <button className="btn-ghost p-1.5" disabled={packageMerging} onClick={() => setPackageMerge(null)} title="关闭"><XCircle size={16} /></button>
            </div>
            <label className="block text-xs text-surface-300">
              Mod 包名称
              <input
                className="mt-2 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-white outline-none focus:border-cyber-cyan"
                value={packageMerge.name}
                maxLength={160}
                disabled={packageMerging}
                onChange={event => setPackageMerge(previous => ({ ...previous, name: event.target.value }))}
              />
            </label>
            <div className="mt-3 rounded-md border border-surface-700 bg-surface-900/70 p-3 text-xs">
              <div className="mb-2 text-surface-400">将合并以下组件：</div>
              <div className="max-h-36 space-y-1 overflow-y-auto text-white/85">
                {packageMerge.items.map(item => <div key={item.id}>• {item.name}</div>)}
              </div>
            </div>
            <p className="mt-3 text-[11px] leading-5 text-cyber-yellow">提示：若这些条目来自不同的官方页面，合并后会保留为“本地包”，避免把不确定来源误标成同一个已核验来源；你仍可重新对齐该整包。</p>
            <div className="mt-4 flex justify-end gap-2">
              <button className="btn-ghost" disabled={packageMerging} onClick={() => setPackageMerge(null)}>取消</button>
              <button className="btn-cyber" disabled={packageMerging || !String(packageMerge.name || '').trim()} onClick={confirmPackageMerge}>
                {packageMerging ? '正在合并…' : '确认合并'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 更新检测只给出候选；用户勾选后才进入更新流水线。 */}
      {updateReview && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => !updatingSelected && setUpdateReview(null)}>
          <div className="bg-surface-800 border border-cyber-cyan/35 rounded-lg p-5 max-w-2xl w-[min(92vw,680px)] max-h-[82vh] flex flex-col shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h3 className="text-base font-semibold text-white">检测到可更新项目</h3>
                <p className="text-xs text-surface-400 mt-1">
                  共检查 {updateReview.summary?.total || mods.length} 项，发现 {updateReview.updates.length} 项可更新。请确认后勾选，不会自动安装。
                </p>
              </div>
              <button className="btn-ghost p-1.5" disabled={updatingSelected} onClick={() => setUpdateReview(null)} title="关闭">
                <XCircle size={16} />
              </button>
            </div>
            <div className="overflow-y-auto space-y-2 pr-1">
              {updateReview.updates.map(item => {
                const checked = updateSelected.has(String(item.mod_id))
                return (
                  <label key={item.mod_id} className="flex items-start gap-3 rounded-md border border-surface-600 bg-surface-900/65 px-3 py-3 cursor-pointer hover:border-cyber-cyan/35">
                    <input
                      type="checkbox"
                      className="mt-1 accent-cyan-400"
                      checked={checked}
                      disabled={updatingSelected}
                      onChange={() => setUpdateSelected(previous => {
                        const next = new Set(previous)
                        if (checked) next.delete(String(item.mod_id))
                        else next.add(String(item.mod_id))
                        return next
                      })}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-white">{item.name}</div>
                      <div className="mt-1 text-xs text-surface-400">
                        {item.current || 'unknown'} → <span className="text-cyber-cyan">{item.latest || '最新版'}</span>
                        <span className="ml-2 text-surface-500">{item.source}</span>
                      </div>
                      {item.status === 'version_unknown' && (
                        <div className="mt-1 text-[11px] text-cyber-yellow">本地版本未知，将按已核验维护页同步最新版</div>
                      )}
                    </div>
                  </label>
                )
              })}
            </div>
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-surface-600 pt-4">
              <button
                className="btn-ghost text-xs"
                disabled={updatingSelected}
                onClick={() => setUpdateSelected(previous => (
                  previous.size === updateReview.updates.length
                    ? new Set()
                    : new Set(updateReview.updates.map(item => String(item.mod_id)))
                ))}
              >
                {updateSelected.size === updateReview.updates.length ? '取消全选' : '全选'}
              </button>
              <div className="flex gap-2">
                <button className="btn-ghost" disabled={updatingSelected} onClick={() => setUpdateReview(null)}>稍后更新</button>
                <button className="btn-cyber" disabled={updatingSelected || !updateSelected.size} onClick={runSelectedUpdates}>
                  {updatingSelected ? '正在更新…' : `更新所选 ${updateSelected.size} 项`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
                <p className="text-surface-500">确认后会先创建 1 份“批量删除前”安全快照，再逐项删除；单项失败会单独报告，不会伪装成全部成功。</p>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setBatchDelete(null)} className="btn-ghost">取消</button>
                <button onClick={confirmBatchDelete} className="tc-danger-button px-4 py-2 rounded-md text-sm bg-cyber-red/80 text-white hover:bg-cyber-red transition-colors">确认全部卸载</button>
              </div>
            </div>
          </div>
        )
      })()}

      {batchProgress && (
        <div className="fixed right-5 bottom-14 z-[60] w-80 rounded-lg border border-cyber-cyan/40 bg-surface-900/95 p-3 shadow-2xl text-xs">
          <div className="flex items-center justify-between gap-3 text-white/90">
            <span>{batchProgress.phase === 'preview' ? '正在核对批量卸载影响' : batchProgress.phase === 'snapshot' ? '正在创建安全快照' : '正在批量删除'}</span>
            <span className="font-mono text-cyber-cyan">{batchProgress.completed}/{batchProgress.total}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded bg-surface-700">
            <div className="h-full bg-cyber-cyan transition-all" style={{ width: `${batchProgress.total ? (batchProgress.completed / batchProgress.total) * 100 : 0}%` }} />
          </div>
          <p className="mt-2 truncate text-surface-400">{batchProgress.current || '准备中…'}</p>
          {batchProgress.phase === 'delete' && <p className="mt-1 text-surface-500">成功 {batchProgress.succeeded || 0} · 失败 {batchProgress.failed || 0}</p>}
        </div>
      )}

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
                <p className="text-xs text-surface-300">{showDeleteConfirm.name_cn || showDeleteConfirm.name}</p>
                {showDeleteConfirm.name_cn && showDeleteConfirm.name_cn !== showDeleteConfirm.name && (
                  <p className="text-[10px] text-surface-500">{showDeleteConfirm.name}</p>
                )}
              </div>
            </div>
            <div className="bg-surface-900 rounded-md p-3 mb-4 text-xs text-surface-400 space-y-1.5">
              <p><span className="text-white/80">功能：</span>{showDeleteConfirm.desc}</p>
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
                {dependencyGate.data.requires_external_manager && (
                  <h3 className="text-sm font-semibold text-white">请在 Steam 中管理启用状态</h3>
                )}
                {!dependencyGate.data.requires_external_manager && <h3 className="text-sm font-semibold text-white">
                  {dependencyGate.data.blocked ? '缺少前置依赖' : dependencyGate.enabling ? '确认启用依赖链' : '确认级联禁用'}
                </h3>}
                <p className="text-xs text-surface-300">{dependencyGate.mod.name_cn || dependencyGate.mod.name}</p>
              </div>
            </div>
            <div className="bg-surface-900 rounded-md p-3 mb-4 text-xs text-surface-400 space-y-2">
              <p><span className="text-white/80">功能：</span>{dependencyGate.mod.desc}</p>
              <p>{dependencyGate.data.note}</p>
              {dependencyGate.data.user_action && <p className="text-cyber-cyan">{dependencyGate.data.user_action}</p>}
              {!!dependencyGate.data.decision_support && (
                <div className="space-y-2 border-l-2 border-cyber-yellow/60 pl-3">
                  <p className="text-white">{dependencyGate.data.decision_support.summary}</p>
                  <p><span className="text-cyber-yellow">你会暂时失去：</span>{dependencyGate.data.decision_support.player_impact?.map(item => `${item.name}（${item.role_label}）：${item.functionality_lost}`).join('；')}</p>
                  {!!dependencyGate.data.decision_support.already_inactive?.length && (
                    <p><span className="text-surface-500">无需重复处理：</span>{dependencyGate.data.decision_support.already_inactive.map(item => item.name).join('、')} 已经禁用</p>
                  )}
                  {!!dependencyGate.data.decision_support.retained?.length && (
                    <p><span className="text-cyber-cyan">仍会保留：</span>{dependencyGate.data.decision_support.retained.map(item => item.name).join('、')}</p>
                  )}
                  <p><span className="text-white/80">为什么建议这样试：</span>{dependencyGate.data.decision_support.why_this_step}</p>
                  <p><span className="text-white/80">建议：</span>{dependencyGate.data.decision_support.recommendation}</p>
                  <p className="text-surface-500">{dependencyGate.data.decision_support.recovery}</p>
                </div>
              )}
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

      {/* 低置信名称不能自动决定身份；把真实候选交给用户确认。 */}
      {alignmentReview && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={() => setAlignmentReview(null)}>
          <div className="bg-surface-800 border border-cyber-yellow/35 rounded-lg p-5 max-w-3xl w-[min(92vw,760px)] max-h-[82vh] overflow-y-auto shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h3 className="text-base font-semibold text-white">需要确认的来源歧义</h3>
                <p className="text-xs text-surface-400 mt-1">
                  “歧义”表示找到了多个相似维护页，但名称相似不足以证明是同一个 Mod。请选择你实际安装的来源；不确定可以暂时跳过。
                </p>
              </div>
              <button className="btn-ghost p-1.5" onClick={() => setAlignmentReview(null)} title="稍后处理">
                <XCircle size={16} />
              </button>
            </div>
            <div className="space-y-4">
              {[...(alignmentReview.items || []), ...(alignmentReview.unmatched || [])].map(item => (
                <div key={item.mod_id} className="rounded-md border border-surface-600 bg-surface-900/70 p-3">
                  <div className="mb-2">
                    <div className="text-sm font-medium text-white">{item.name}</div>
                    <div className="text-[11px] text-cyber-yellow">{item.reason || '候选相似，需要人工确认'}</div>
                  </div>
                  <div className="space-y-2">
                    {(item.candidates || []).map(candidate => (
                      <div key={`${candidate.source}:${candidate.source_key}`} className="flex items-start justify-between gap-3 rounded border border-surface-700 bg-surface-800 px-3 py-2">
                        <div className="min-w-0">
                          <div className="text-xs text-white">
                            {candidate.name || candidate.source_key}
                            <span className="ml-2 text-surface-500">{candidate.source}</span>
                          </div>
                          <div className="mt-1 text-[10px] text-surface-400">
                            {candidate.owner ? `作者 ${candidate.owner} · ` : ''}
                            {candidate.latest_version || candidate.version ? `版本 ${candidate.latest_version || candidate.version} · ` : ''}
                            匹配度 {Math.round((Number(candidate.score) || 0) * 100)}%
                          </div>
                          {(candidate.description || candidate.summary) && (
                            <div className="mt-1 text-[11px] text-surface-300 line-clamp-2">
                              {candidate.description || candidate.summary}
                            </div>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col gap-1">
                          {candidate.url && (
                            <button
                              className="btn-ghost text-xs"
                              onClick={() => window.modagent?.openExternal?.(candidate.url)}
                            >
                              查看维护页
                            </button>
                          )}
                          <button
                            className="btn-cyber text-xs"
                            disabled={!!actionLock}
                            onClick={() => confirmAlignmentCandidate(item, candidate)}
                          >
                            {actionLock === `align:${item.mod_id}` ? (
                              <span className="inline-flex items-center gap-1.5">
                                <RefreshCw size={12} className="animate-spin" />
                                确认中
                              </span>
                            ) : '确认此来源'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 border-t border-surface-700 pt-3">
                    <div className="text-[11px] text-surface-400 mb-2">
                      如果你知道它来自哪里，可直接粘贴 Nexus / Thunderstore 的具体 Mod 维护页。ModAgent 会先核验，再由你确认绑定。
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <input
                        value={manualSource[item.mod_id] || ''}
                        onChange={event => setManualSource(previous => ({
                          ...previous, [item.mod_id]: event.target.value,
                        }))}
                        placeholder="手动添加网址并检查"
                        className="input-cyber flex-1 text-xs"
                      />
                      <button
                        className="btn-ghost text-xs shrink-0"
                        disabled={!!actionLock}
                        onClick={() => inspectManualSource(item)}
                      >
                        {actionLock === `manual-source:${item.mod_id}` ? '检查中…' : '检查网址'}
                      </button>
                      <button
                        className="btn-ghost text-xs shrink-0"
                        disabled={binding || !!actionLock}
                        onClick={() => runAlignment([item], true)}
                      >
                        重新对齐
                      </button>
                    </div>
                    {manualSourcePreview[item.mod_id] && (
                      <div className="mt-2 flex items-center justify-between gap-3 rounded border border-cyber-cyan/35 bg-cyber-cyan/5 px-3 py-2">
                        <div className="min-w-0 text-[11px] text-surface-200">
                          已核验：{manualSourcePreview[item.mod_id].preview?.nexus?.name || manualSourcePreview[item.mod_id].preview?.source?.name || manualSourcePreview[item.mod_id].source_key}
                        </div>
                        <button
                          className="btn-cyber text-xs shrink-0"
                          disabled={!!actionLock}
                          onClick={() => confirmManualSource(item)}
                        >确认绑定</button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-end">
              <button className="btn-ghost" onClick={() => setAlignmentReview(null)}>暂时跳过</button>
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
