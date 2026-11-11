import React, { useState, useEffect, useRef } from 'react'
import { saveSetupConfiguration, setupFailureMessage } from '../setupWorkflow.mjs'
import {
  BookOpen, Copy, Cpu, FileDown, FileText, FolderCog, FolderOpen,
  Github, Globe, HardDrive, Image, Info, Key, PanelLeft, RefreshCw,
  Scale, Trash2,
} from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { SettingsEditionPanel, applyEditionDefaultBackground } from '@edition'
import { isPAccessEnabled, usePLicenseStatus } from '../license/pLicense'
import { activatePShare, usePShareProfile } from '../pshare/pShareStore'
import {
  readLayoutPreference,
  saveLayoutPreference,
} from '../theme/layoutPreference'
import { LANGUAGES, tr } from '../i18n'
import ConnectionTestPanel from './ConnectionTestPanel'
import BrowserControls from './BrowserControls'
import {CredentialHelp} from './CredentialGuide'
import {requestLocalJson, localApiFailure} from './localApi.mjs'
import {validateRuntimeStatus} from '../runtimeStatus.mjs'
import {readShareResult, validateSharePreview, validateShareExport, shareRejectionMessage} from './shareResponse.mjs'
import {validateOfficialCatalog, validateOfficialDiagnostics, validateOfficialPreview} from './officialShareResponse.mjs'
import {sharePrerequisitesPending} from './sharePlan.mjs'
import {runMaintenanceAction, maintenanceFailure} from '../maintenanceActions.mjs'
import {checkDesktopUpdate} from '../updateCheck.mjs'

const COMMON_LEGAL_DOCUMENTS = [
  { file: 'LICENSE.md', label: '软件许可证' },
  { file: 'PRIVACY.md', label: '隐私说明' },
  { file: 'THIRD-PARTY-MODS-DISCLAIMER.md', label: '第三方 Mod 与网站免责声明' },
  { file: 'THIRD_PARTY_NOTICES.md', label: '第三方软件声明' },
]
const SUBSCRIPTION_LEGAL_DOCUMENTS = [
  { file: 'SUBSCRIPTION-REFUND-SUPPORT.md', label: 'P 会员、退款与支持说明' },
  { file: 'SUBSCRIPTION-SOFTWARE-LICENSE.md', label: 'P 版软件许可' },
  { file: 'PROPRIETARY-ASSETS-LICENSE.md', label: 'P 专属素材许可' },
]
const LEGAL_DOCUMENTS = __MODAGENT_SUBSCRIPTION__
  ? [...COMMON_LEGAL_DOCUMENTS, ...SUBSCRIPTION_LEGAL_DOCUMENTS]
  : COMMON_LEGAL_DOCUMENTS
const LLM_PRESETS = [
  ['deepseek', 'DeepSeek', 'https://api.deepseek.com/v1', 'deepseek-v4-pro'],
  ['openai', 'OpenAI / GPT', 'https://api.openai.com/v1', 'gpt-4.1'],
  ['custom', '自定义兼容接口', '', ''],
]
const MODEL_OPTIONS = [
  ['deepseek-v4-pro', 'DeepSeek V4 Pro'],
  ['deepseek-v4-flash', 'DeepSeek V4 Flash'],
  ['gpt-4.1', 'OpenAI GPT（示例）'],
  ['custom', '自定义模型名'],
]

export default function SettingsPage({ toast, api, language = 'zh-CN', onLanguageChange, onStartSharePlan, onPShareActivated }) {
  const ui = (zh, en) => language === 'en' ? en : zh
  const pLicense = usePLicenseStatus()
  const pShareProfile = usePShareProfile()
  const identity = window.modagent?.getAppIdentity?.() || {
    productName: __MODAGENT_SUBSCRIPTION__ ? 'ModAgent P' : 'ModAgent',
    version: __MODAGENT_VERSION__,
    channel: 'stable',
  }
  const [cfg, setCfg] = useState({})
  const [settingsLoad, setSettingsLoad] = useState('loading')
  const [settingsLoadError, setSettingsLoadError] = useState(null)
  const [settingsLoadAttempt, setSettingsLoadAttempt] = useState(0)
  const [credentialStatus, setCredentialStatus] = useState(null)
  const [savingCredentials, setSavingCredentials] = useState(false)
  const saveLockRef = useRef(false)
  const [saveRestartRequired, setSaveRestartRequired] = useState(false)
  const [nexusKey, setNexusKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [editingKeys, setEditingKeys] = useState({
    nexus: false, tavily: false, llm: false,
  })
  const [model, setModel] = useState('deepseek-v4-pro')
  const [customModel, setCustomModel] = useState('')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [recommendationLimit, setRecommendationLimit] = useState(10)
  const [agentCoreMode, setAgentCoreMode] = useState('off')
  const [layoutMode, setLayoutMode] = useState(readLayoutPreference)
  const [bg, setBg] = useState(null)
  const [bgUrl, setBgUrl] = useState(null)
  const [shareInput, setShareInput] = useState('')
  const [sharePreview, setSharePreview] = useState(null)
  const sharePreviewLock = useRef(false)
  const [shareBusy, setShareBusy] = useState(false)
  const [shareNote, setShareNote] = useState('')
  const [shareSnapshots, setShareSnapshots] = useState(false)
  const [officialQuery, setOfficialQuery] = useState('')
  const [officialCatalog, setOfficialCatalog] = useState(null)
  const [officialBusy, setOfficialBusy] = useState(false)
  const officialLock = useRef(false)
  const [creatorName, setCreatorName] = useState('')
  const diagnosticExportLock = useRef(false)
  const [exportingDiagnostics, setExportingDiagnostics] = useState(false)
  const maintenanceLock = useRef(false)
  const [maintenanceBusy, setMaintenanceBusy] = useState(false)
  const updateCheckLock = useRef(false)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const backgroundLock = useRef(false)
  const [backgroundBusy, setBackgroundBusy] = useState(false)

  const activateCreatorProfile = () => {
    if (!isPAccessEnabled(pLicense)) {
      toast('需要先完成有效的 ModAgent P 会员验证。', 'error')
      return
    }
    activatePShare(creatorName)
    toast('P Share 创作者计划已开通。')
    onPShareActivated?.()
  }

  useEffect(() => {
    let stale = false
    const controller = new AbortController()
    setSettingsLoad('loading')
    setSettingsLoadError(null)
    window.modagent?.getCredentialStatus?.().then(s => { if (!stale) setCredentialStatus(s) }).catch(() => {})
    requestLocalJson(api + '/status', {signal: controller.signal}).then(s => {
      if (stale) return
      validateRuntimeStatus(s)
      setCfg(s)
      if (s.language === 'en' || s.language === 'zh-CN') onLanguageChange?.(s.language)
      const loadedModel = s.llm_model || 'deepseek-v4-pro'
      const knownModel = MODEL_OPTIONS.some(([value]) => value === loadedModel)
      setModel(knownModel ? loadedModel : 'custom')
      setCustomModel(knownModel ? '' : loadedModel)
      setEndpoint(s.llm_endpoint || 'https://api.deepseek.com/v1')
      setRecommendationLimit(Math.max(2, Math.min(Number(s.recommendation_limit) || 10, 20)))
      setAgentCoreMode(['off', 'shadow', 'on'].includes(s.agent_core_v2) ? s.agent_core_v2 : 'off')
      setBg(s.bg || null)
      if (s.bg) window.modagent?.getBgDataUrl?.(s.bg).then(url => { if (!stale) setBgUrl(url) }).catch(() => {})
      setSettingsLoad('ready')
    }).catch(error => {
      if (stale) return
      setSettingsLoadError(error)
      setSettingsLoad('error')
    })
    return () => { stale = true; controller.abort() }
  }, [api, settingsLoadAttempt])

  const pickBg = async () => {
    if (backgroundLock.current) return
    backgroundLock.current = true; setBackgroundBusy(true)
    try {
      const name = await window.modagent.selectBg()
      if (name) {
        const dataUrl = await window.modagent.getBgDataUrl(name)
        if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) throw Error('invalid background preview')
        setBg(name)
        setBgUrl(dataUrl)
        document.body.classList.add('has-bg')
        document.body.style.backgroundImage = dataUrl ? `url("${dataUrl}")` : ''
        emitFeedback('notice', { source: 'background' })
        toast(language === 'en' ? 'Background updated.' : '背景已更新。')
      }
    } catch (_) { emitFeedback('error', { source: 'background' }); toast(language === 'en' ? '[BACKGROUND_CHANGE_FAILED] Background change was not confirmed. Check that the image opens correctly and is no larger than 32 MiB.' : '[BACKGROUND_CHANGE_FAILED] 尚未确认背景更换成功，请检查图片能正常打开且不超过 32 MiB。', 'error') }
    finally { backgroundLock.current = false; setBackgroundBusy(false) }
  }

  const removeBg = async () => {
    if (backgroundLock.current) return
    backgroundLock.current = true; setBackgroundBusy(true)
    try {
      if (await window.modagent.removeBg() !== true) throw Error('unconfirmed')
      setBg(null)
      setBgUrl(null)
      applyEditionDefaultBackground()
      emitFeedback('remove-complete', { source: 'background' })
      toast(language === 'en' ? 'Custom background removed.' : '自定义背景已移除。')
    } catch (_) { emitFeedback('error', { source: 'background' }); toast(language === 'en' ? '[BACKGROUND_REMOVE_FAILED] Removal was not confirmed. Check the current background before retrying.' : '[BACKGROUND_REMOVE_FAILED] 尚未确认移除成功，请检查当前背景后再试。', 'error') }
    finally { backgroundLock.current = false; setBackgroundBusy(false) }
  }


  const checkAppUpdate = async () => {
    if (updateCheckLock.current) return
    updateCheckLock.current = true; setCheckingUpdate(true)
    try {
      const result = await checkDesktopUpdate(window.modagent)
      if (result.disabled) {
        toast(language === 'en' ? 'Updates are disabled for this isolated test build. Use the separately supplied candidate package.' : '独立测试包已禁用更新，请使用单独提供的新候选包。')
        return
      }
      if (result.available) {
        if (result.downloadPage) {
          toast(language === 'en' ? `Version ${result.version} is available. Opening the download page.` : `发现新版本 v${result.version}，正在打开下载页面`)
          await openProjectLink(result.downloadPage)
        } else {
          toast(language === 'en' ? `Version ${result.version} is available. Follow the app update prompt or use your original download page.` : `发现新版本 v${result.version}，请按应用更新提示操作或前往原下载页面。`)
        }
        return
      }
      toast(language === 'en' ? `No newer version was reported for this channel. Installed: ${identity.version}.` : `当前渠道未报告更新版本，已安装版本：${identity.version}。`)
    } catch (error) {
      toast(error?.message === 'UPDATE_TIMEOUT'
        ? (language === 'en' ? '[UPDATE_TIMEOUT] The update check did not reply in time; it may still be running. No current-version result was confirmed.' : '[UPDATE_TIMEOUT] 更新检查未及时回复，后台可能仍在检查；尚未确认是否有新版本。')
        : (language === 'en' ? '[UPDATE_CHECK_FAILED] Could not verify updates. Check the app connection and try again; this does not mean you are up to date.' : '[UPDATE_CHECK_FAILED] 无法核验更新，请检查应用连接后再试；这不代表已是最新版。'), 'error')
    } finally {updateCheckLock.current = false; setCheckingUpdate(false)}
  }

  const maintenanceAction = async kind => {
    if (maintenanceLock.current) return
    maintenanceLock.current = true; setMaintenanceBusy(true)
    try {
      await runMaintenanceAction(kind, {bridge:window.modagent})
      if (kind === 'copyLogs') toast(language === 'en' ? 'Log folder path copied.' : '日志目录路径已复制。')
    } catch (error) { toast(maintenanceFailure(error, language), 'error') }
    finally { maintenanceLock.current = false; setMaintenanceBusy(false) }
  }

  const openProjectLink = async url => {
    try {
      const result = await window.modagent?.openExternal?.(url)
      if (!result?.ok) throw new Error(result?.error || 'blocked')
    } catch (_) {
      toast('无法打开链接', 'error')
    }
  }

  const exportDiagnostics = async () => {
    if (diagnosticExportLock.current) return
    diagnosticExportLock.current = true
    setExportingDiagnostics(true)
    try {
      const output = await window.modagent?.exportRuntimeDiagnostics?.(language)
      if (output?.cancelled) return
      if (output?.ok !== true || typeof output.filename !== 'string' || !output.filename) throw new Error('unconfirmed')
      toast(language === 'en' ? 'Diagnostics exported. Review the report before sharing.' : '诊断信息已导出，分享前请检查报告内容。')
    } catch (_) {
      toast(language === 'en' ? '[DIAGNOSTICS_EXPORT_FAILED] Export was not confirmed. Check the save location and available disk space, then retry.' : '[DIAGNOSTICS_EXPORT_FAILED] 尚未确认导出成功，请检查保存位置和磁盘空间后重试。', 'error')
    } finally { diagnosticExportLock.current = false; setExportingDiagnostics(false) }
  }

  const callShareTool = async (name, body = {}) => {
    const data = await requestLocalJson(`${api}/tool/${name}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }, {timeoutMs:30000})
    return readShareResult(data)
  }
  const shareFailure = error => '[SETTINGS_SHARE_FAILED] ' + (error?.code === 'SHARE_VERIFICATION_REJECTED'
    ? shareRejectionMessage(language) : localApiFailure(error, language))

  const downloadShare = async () => {
    if (sharePreviewLock.current) return
    sharePreviewLock.current = true
    setShareBusy(true)
    let generated = false
    try {
      const result = validateShareExport(await callShareTool('share_export', {
        author_note: shareNote, include_snapshots: shareSnapshots,
      }))
      generated = true
      const filename = `modagent-share-${Date.now()}.json`
      if (window.modagent?.saveShareFile) {
        const saved = await window.modagent.saveShareFile({text:result.share_json, filename})
        if (saved?.cancelled) {
          toast(language === 'en' ? 'Save cancelled. Your draft is retained.' : '已取消保存，草稿已保留。')
          return
        }
        if (saved?.ok !== true || typeof saved.filename !== 'string') throw Error('share_save_failed')
        toast(language === 'en' ? 'Configuration JSON saved. Nothing has been uploaded.' : '配置 JSON 已保存，尚未上传到任何网站。')
        return
      }
      const blob = new Blob([result.share_json], { type: 'application/json;charset=utf-8' })
      const href = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = href
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(href)
      toast(language === 'en' ? '[SHARE_SAVE_UNCONFIRMED] Download requested; check the downloaded JSON. This browser cannot confirm it was saved.' : '[SHARE_SAVE_UNCONFIRMED] 已请求下载，请核对下载的 JSON；浏览器无法确认是否保存成功。', 'warn')
    } catch (error) { toast(generated
      ? '[SETTINGS_SHARE_SAVE_FAILED] ' + (language === 'en' ? 'Content was generated, but saving was not confirmed. Check the destination and available storage before retrying.' : '内容已生成，但保存尚未确认。请检查目标文件和可用空间后再试。')
      : shareFailure(error), 'error') }
    finally { setShareBusy(false); sharePreviewLock.current = false }
  }

  const copyOfflineShareLink = async () => {
    if (sharePreviewLock.current) return
    sharePreviewLock.current = true
    setShareBusy(true)
    try {
      const result = await callShareTool('share_export', {
        author_note: shareNote, include_snapshots: shareSnapshots,
      })
      if (typeof result.offline_share_link !== 'string' || !/^data:application\/vnd\.modagent-share\+json;base64,[A-Za-z0-9+/]+={0,2}$/.test(result.offline_share_link)) throw Error('invalid_share_link')
      await navigator.clipboard.writeText(result.offline_share_link)
      toast('离线分享链接已复制。配置较多时建议改用导出的 JSON/Gist。')
    } catch (_) { toast('复制分享链接失败', 'error') }
    finally { setShareBusy(false); sharePreviewLock.current = false }
  }

  const inspectShare = async () => {
    if (sharePreviewLock.current) return
    if (!shareInput.trim()) { toast('请粘贴 JSON、离线链接或 GitHub Raw/Gist 链接', 'error'); return }
    const input = shareInput.trim()
    sharePreviewLock.current = true
    setSharePreview(null)
    setShareBusy(true)
    try {
      const result = validateSharePreview(await callShareTool('share_import', { share: input }))
      setSharePreview({...result, _verifiedInput:input})
      toast(`已解析分享：${result.summary?.total || 0} 个 Mod，尚未安装或修改任何内容。`)
    } catch (error) { toast(shareFailure(error), 'error') }
    finally { setShareBusy(false); sharePreviewLock.current = false }
  }

  const loadOfficialCatalog = async () => {
    if (officialLock.current) return
    officialLock.current = true
    setOfficialBusy(true)
    setOfficialCatalog(null)
    try {
      const result = validateOfficialCatalog(await callShareTool('official_share_catalog', { query: officialQuery.trim() }))
      setOfficialCatalog(result)
      if (result.source === 'local_cache') {
        const age = Number(result.cache_age_seconds || 0)
        const ageText = age >= 3600 ? `${Math.floor(age / 3600)} 小时前` : '刚才'
        toast(`官方库网络暂不可用，已使用 ${ageText} 保存的本地验证缓存。`, 'warn')
      } else if (!result.available && !result.fetched) {
        toast('官方库暂时无法读取，且本机没有可用缓存；未修改任何本地安装。', 'error')
      }
    } catch (error) { toast('[OFFICIAL_CATALOG_FAILED] ' + localApiFailure(error, language), 'error') }
    finally { setOfficialBusy(false); officialLock.current = false }
  }

  const diagnoseOfficialCatalogNetwork = async () => {
    if (officialLock.current) return
    officialLock.current = true
    setOfficialBusy(true)
    try {
      const result = validateOfficialDiagnostics(await callShareTool('official_share_network_diagnostics'))
      const working = (result.checks || []).filter(item => item.ok).map(item => item.endpoint)
      if (working.length) {
        toast(`官方库连接可用：${working.join(' / ')}。`, 'success')
      } else if (!result.checks.length) {
        toast(language === 'en' ? '[OFFICIAL_CHECK_EMPTY] No endpoint was checked. Connectivity is unknown.' : '[OFFICIAL_CHECK_EMPTY] 未实际检测任何入口，无法判断连接状态。', 'warn')
      } else if (result.cache_available) {
        toast('官方库网络暂不可达，但本机仍有可用验证缓存。', 'warn')
      } else {
        toast('Raw、GitHub API 和 GitHub 网页文件入口均不可达，且本机没有缓存。', 'error')
      }
    } catch (error) { toast('[OFFICIAL_CHECK_FAILED] ' + localApiFailure(error, language), 'error') }
    finally { setOfficialBusy(false); officialLock.current = false }
  }

  const openOfficialCollection = async (shareId) => {
    if (sharePreviewLock.current || officialLock.current) return
    officialLock.current = true
    sharePreviewLock.current = true
    setSharePreview(null)
    setOfficialBusy(true)
    try {
      const result = validateOfficialPreview(await callShareTool('official_share_import', { share_id: shareId }), shareId)
      setSharePreview(result)
      toast(`已打开官方合集 ${shareId}；尚未安装或修改任何内容。`)
    } catch (error) { toast(shareFailure(error), 'error') }
    finally { setOfficialBusy(false); sharePreviewLock.current = false; officialLock.current = false }
  }

  const openLegalDocument = async (file) => {
    try {
      const error = await window.modagent?.openLegalDocument?.(file)
      if (error) throw new Error(error)
    } catch (_) {
      toast('无法打开法律文件，请重新安装或检查发行包完整性', 'error')
    }
  }

  const save = async () => {
    if (saveLockRef.current || saveRestartRequired || settingsLoad !== 'ready') return
    const effectiveModel = model === 'custom' ? customModel.trim() : model
    if (!effectiveModel) {
      toast('请填写模型名', 'error')
      return
    }
    if (!endpoint.trim()) {
      toast('请填写 LLM 接口地址', 'error')
      return
    }
    const body = {
      llm_model: effectiveModel,
      llm_endpoint: endpoint.trim(),
      recommendation_limit: Math.max(2, Math.min(Number(recommendationLimit) || 10, 20)),
      language,
      agent_core_v2: agentCoreMode,
    }
    if (nexusKey && nexusKey !== '********') body.api_key = nexusKey
    if (llmKey && llmKey !== '********') body.llm_api_key = llmKey
    if (tavilyKey && tavilyKey !== '********') body.tavily_api_key = tavilyKey
    saveLockRef.current = true
    setSavingCredentials(true)
    try {
    const saved = await saveSetupConfiguration(api, body, {store: window.modagent?.saveSecrets})
    if (saved.status) setCredentialStatus(saved.status)
    setCfg(prev => ({
      ...prev,
      api_key_set: saved.status?.api_key_set ?? (prev.api_key_set || Boolean(nexusKey)),
      tavily_set: saved.status?.tavily_set ?? (prev.tavily_set || Boolean(tavilyKey)),
      llm_set: saved.status?.llm_set ?? (prev.llm_set || Boolean(llmKey)),
    }))
    setNexusKey('')
    setTavilyKey('')
    setLlmKey('')
    setEditingKeys({ nexus: false, tavily: false, llm: false })
    emitFeedback('success', { source: 'settings' })
    toast(tr(language, 'languageSaved'))
    } catch (error) {
      if (error.restartRequired) setSaveRestartRequired(true)
      toast(setupFailureMessage(error, language).replace('[SETUP_', '[SETTINGS_'), 'error')
    } finally {
      setSavingCredentials(false)
      saveLockRef.current = false
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center px-4 py-3 border-b border-surface-600">
        <h2 className="text-base font-semibold flex items-center gap-2">
          <Cpu size={16} className="text-cyber-cyan" /> {tr(language, 'settingsTitle')}
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto p-6 max-w-2xl w-full space-y-5">
        <ConnectionTestPanel api={api} language={language} />
        <BrowserControls language={language}/>
        {settingsLoad !== 'ready' ? <div role="status" className="card-cyber space-y-3">
          <p>{settingsLoad === 'loading'
            ? (language === 'en' ? 'Loading existing settings…' : '正在读取已有设置…')
            : '[SETTINGS_LOAD_FAILED] ' + localApiFailure(settingsLoadError, language)}</p>
          <p className="text-xs text-surface-500">{language === 'en'
            ? 'Editing is unavailable until existing settings are loaded. No defaults have been saved.'
            : '读取已有设置后才能编辑，未将默认值写入配置。'}</p>
          {settingsLoad === 'error' && <button className="btn-cyber" onClick={() => setSettingsLoadAttempt(x => x + 1)}>{language === 'en' ? 'Retry loading settings' : '重新读取设置'}</button>}
        </div> : <>
        <div className="card-cyber space-y-2">
          <div className="flex items-center gap-2">
            <Globe size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">{tr(language, 'language')}</span>
          </div>
          <select className="input-cyber" value={language} onChange={e => onLanguageChange?.(e.target.value)}>
            {LANGUAGES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <p className="text-[11px] leading-relaxed text-surface-500">{tr(language, 'languageHelp')}</p>
        </div>
        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Key size={14} className="text-cyber-yellow" />
            <span className="text-sm font-medium">{tr(language, 'apiKeys')}</span>
          </div>
          {credentialStatus && <p className="text-xs text-surface-500">
            {language === 'en'
              ? (credentialStatus.origin === 'shared' ? 'Using shared encrypted credentials. ' : 'Using this profile’s credentials. ')
              : (credentialStatus.origin === 'shared' ? '正在复用本机加密凭据。' : '正在使用当前配置的凭据。')}
            {credentialStatus.localOnly
              ? (language === 'en' ? 'Changes in this test build stay local.' : '测试版修改仅保存在当前测试配置，不影响正式版。')
              : (language === 'en' ? 'Saved credentials are reusable by supported versions on this Windows account.' : '保存后，同一 Windows 用户下支持此功能的版本可复用。')}
          </p>}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">Nexus Mods API Key</label>
              {cfg.api_key_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setNexusKey(''); setEditingKeys(v => ({ ...v, nexus: true })) }}>
                <RefreshCw size={11} /> {ui('重新输入', 'Replace key')}
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.api_key_set ? ui('已设置', 'Configured') : ui('未设置', 'Not configured')}
              value={nexusKey}
              disabled={cfg.api_key_set && !editingKeys.nexus}
              onChange={e => setNexusKey(e.target.value)}
            />
            <CredentialHelp provider="nexus" language={language} toast={toast}/>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">Tavily Search API Key</label>
              {cfg.tavily_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setTavilyKey(''); setEditingKeys(v => ({ ...v, tavily: true })) }}>
                <RefreshCw size={11} /> {ui('重新输入', 'Replace key')}
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.tavily_set ? ui('已设置', 'Configured') : ui('未设置（完整跨站搜索所需）', 'Not configured (needed for full cross-site search)')}
              value={tavilyKey}
              disabled={cfg.tavily_set && !editingKeys.tavily}
              onChange={e => setTavilyKey(e.target.value)}
            />
            <CredentialHelp provider="tavily" language={language} toast={toast}/>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">LLM API Key</label>
              {cfg.llm_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setLlmKey(''); setEditingKeys(v => ({ ...v, llm: true })) }}>
                <RefreshCw size={11} /> {ui('重新输入', 'Replace key')}
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.llm_set ? ui('已设置', 'Configured') : ui('未设置', 'Not configured')}
              value={llmKey}
              disabled={cfg.llm_set && !editingKeys.llm}
              onChange={e => setLlmKey(e.target.value)}
            />
            <CredentialHelp provider={endpoint.trim()==='https://api.deepseek.com/v1'?'deepseek':endpoint.trim()==='https://api.openai.com/v1'?'openai':'custom'} language={language} toast={toast}/>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Cpu size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">{tr(language, 'llmSettings')}</span>
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">{ui('服务商快捷预设', 'Provider presets')}</label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {LLM_PRESETS.map(([value, label, presetEndpoint, presetModel]) => (
                <button
                  key={value}
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={() => {
                    if (presetEndpoint) setEndpoint(presetEndpoint)
                    if (presetModel) {
                      setModel(presetModel)
                      setCustomModel('')
                    } else {
                      setModel('custom')
                    }
                  }}
                >
                  {value === 'custom' ? ui(label, 'Custom compatible API') : label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">
              {language === 'en' ? 'Agent Core' : 'Agent 新内核（测试）'}
            </label>
            <select className="input-cyber" value={agentCoreMode} onChange={e => setAgentCoreMode(e.target.value)}>
              <option value="off">{language === 'en' ? 'Legacy · compatibility' : '旧版 · 兼容模式'}</option>
              <option value="shadow">{language === 'en' ? 'Observe · no behavior change' : '观察模式 · 不改变现有行为'}</option>
              <option value="on">{language === 'en' ? 'Agent Core v2 · enable' : 'Agent Core v2 · 启用新版'}</option>
            </select>
            <p className="mt-1 text-[11px] leading-relaxed text-surface-500">
              {language === 'en'
                ? 'Observe records task routing without changing tool behavior. v2 enforces task-specific tool permissions and can be switched back at any time.'
                : '观察模式只记录任务判断，不改变工具行为；启用新版后会按任务限制工具权限，出现问题可随时切回旧版。'}
            </p>
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">{ui('模型', 'Model')}</label>
            <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
              {MODEL_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>{value === 'custom' ? ui(label, 'Custom model ID') : value === 'gpt-4.1' ? ui(label, 'OpenAI GPT (example)') : label}</option>
              ))}
            </select>
          </div>
          {model === 'custom' && (
            <div>
              <label className="text-xs text-surface-500 block mb-1">{ui('自定义模型名', 'Custom model ID')}</label>
              <input
                className="input-cyber"
                value={customModel}
                onChange={e => setCustomModel(e.target.value)}
                placeholder={ui('填写服务商文档中的模型 ID', 'Enter the model ID from your provider documentation')}
              />
            </div>
          )}
          <div>
            <label className="text-xs text-surface-500 block mb-1">{ui('接口地址', 'API endpoint')}</label>
            <div className="flex items-center gap-2">
              <Globe size={14} className="text-surface-500" />
              <input className="input-cyber" value={endpoint} onChange={e => setEndpoint(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Cpu size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">{ui('智能推荐', 'Recommendations')}</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <label htmlFor="recommendation-limit" className="text-xs text-surface-400">
                {ui('最大候选数', 'Maximum candidates')}
              </label>
              <p className="mt-1 text-[11px] leading-relaxed text-surface-500">
                {ui('默认 10 个，可设置为 2–20 个；实际数量取决于本轮有效搜索结果。', 'Default: 10; range: 2–20. The actual count depends on valid results from this search.')}
              </p>
            </div>
            <input
              id="recommendation-limit"
              type="number"
              min="2"
              max="20"
              step="1"
              className="input-cyber w-20 text-center"
              value={recommendationLimit}
              onChange={event => setRecommendationLimit(event.target.value)}
              onBlur={() => setRecommendationLimit(
                Math.max(2, Math.min(Number(recommendationLimit) || 10, 20))
              )}
            />
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <PanelLeft size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">{ui('界面布局', 'Interface layout')}</span>
          </div>
          <p className="text-xs leading-relaxed text-surface-500">
            {ui('只调整区域比例、留白和分区轮廓，不改变按钮含义与操作流程。', 'Changes panel proportions, spacing and outlines only. Controls and workflows stay the same.')}
          </p>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={ui('界面布局', 'Interface layout')}>
            {[
              ['plain', ui('朴素版', 'Simple'), ui('规整矩形与均衡间距', 'Regular panels with balanced spacing')],
              ['designed', ui('设计版', 'Designed'), ui('黄金比例与非对称分区', 'Golden-ratio proportions and asymmetric panels')],
            ].map(([value, label, note]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={layoutMode === value}
                className={`layout-choice text-left ${layoutMode === value ? 'is-active' : ''}`}
                onClick={() => {
                  const next = saveLayoutPreference(value)
                  setLayoutMode(next)
                  emitFeedback('notice', { source: 'layout', layout: next })
                  toast(ui(`已切换为${label}`, `Layout changed to ${label}.`))
                }}
              >
                <span className="block text-xs font-medium text-white">{label}</span>
                <span className="mt-1 block text-[10px] leading-relaxed text-surface-500">{note}</span>
              </button>
            ))}
          </div>
        </div>

        <SettingsEditionPanel toast={toast} />

        {__MODAGENT_SUBSCRIPTION__ && (
          <div className="card-cyber space-y-3">
            <div className="flex items-center gap-2">
              <Github size={14} className="text-cyber-cyan" />
              <span className="text-sm font-medium">P Share · 创作者计划</span>
              {pShareProfile && <span className="ml-auto rounded-full bg-cyber-green/10 px-2 py-0.5 text-[10px] text-cyber-green">已开通</span>}
            </div>
            {pShareProfile ? (
              <div className="rounded-lg border border-cyber-green/25 bg-cyber-green/5 p-3 text-xs text-surface-300">
                <p>{pShareProfile.display_name || 'P Share 创作者'} 已具备投稿资格。导出仅允许包含已对齐、可复核原始页面的 Mod。</p>
                <button type="button" className="btn-ghost mt-3 text-xs" onClick={() => onPShareActivated?.()}>进入分享者主页</button>
              </div>
            ) : (
              <>
                <p className="text-xs leading-relaxed text-surface-500">通过 P 授权后开通创作者档案，即可导出审核投稿包并追踪自己的投稿状态。档案只保存在本机。</p>
                <input className="input-cyber text-xs" maxLength={80} value={creatorName} onChange={event => setCreatorName(event.target.value)} placeholder="创作者显示名（可选）" />
                <button type="button" className="btn-cyber w-full" onClick={activateCreatorProfile} disabled={!isPAccessEnabled(pLicense)}>开通 P Share 创作者计划</button>
                {!isPAccessEnabled(pLicense) && <p className="text-[11px] text-cyber-yellow">请先在 P 会员验证中完成授权验证。</p>}
              </>
            )}
          </div>
        )}

        {/* Share creation moved to selected Mods; importing moved to the home quick actions. */}
        <div className="hidden" aria-hidden="true">
        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <FileText size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">分享配置（Beta）</span>
          </div>
          <p className="text-xs leading-relaxed text-surface-500">
            导出的是可审核的 Mod 清单：名称、来源、依赖、启用状态和排序。不会包含 API Key、游戏路径、已安装文件路径或配置文件内容。
          </p>
          <input
            className="input-cyber text-xs"
            value={shareNote}
            maxLength={2000}
            onChange={event => setShareNote(event.target.value)}
            placeholder="作者备注（可选，例如：适合联机/建议先备份存档）"
          />
          <label className="flex items-center gap-2 text-xs text-surface-400 cursor-pointer">
            <input type="checkbox" checked={shareSnapshots} onChange={event => setShareSnapshots(event.target.checked)} />
            附带快照元数据（仅名称、时间和可用状态；不包含快照文件）
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button type="button" disabled={shareBusy} onClick={downloadShare} className="btn-ghost flex items-center justify-center gap-1.5">
              <FileDown size={13} /> 导出配置 JSON
            </button>
            <button type="button" disabled={shareBusy} onClick={copyOfflineShareLink} className="btn-ghost flex items-center justify-center gap-1.5">
              <Copy size={13} /> 复制离线分享链接
            </button>
          </div>
          <textarea
            className="input-cyber min-h-24 resize-y text-xs"
            value={shareInput}
            readOnly={shareBusy || officialBusy}
            onChange={event => {setShareInput(event.target.value); setSharePreview(null)}}
            placeholder="粘贴 ModAgent JSON、离线分享链接、GitHub Raw 或 Gist Raw 链接"
          />
          <button type="button" disabled={shareBusy} onClick={inspectShare} className="btn-cyber w-full disabled:opacity-50">
            {shareBusy ? '正在解析…' : '解析并核验分享配置'}
          </button>
          {sharePreview && (
            <div className="rounded-lg border border-surface-600/80 bg-surface-900/45 p-3 text-xs space-y-2">
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-surface-300">
                <span>共 {sharePreview.summary?.total || 0} 个</span>
                <span>已安装 {sharePreview.summary?.already_installed || 0}</span>
                <span>待核验 {sharePreview.summary?.needs_verification || 0}</span>
                <span>待补来源 {sharePreview.summary?.needs_source_resolution || 0}</span>
              </div>
              <p className="text-surface-500">已完成只读预览；生成安装计划前仍会核验来源、依赖、冲突与当前游戏适配。</p>
              {sharePreview?.source_kind !== 'official_collection' && sharePreview._verifiedInput === shareInput.trim() && sharePreview.items.length > 0 && (
                <button type="button" onClick={() => onStartSharePlan?.(sharePrerequisitesPending(sharePreview)
                  ? {type:'private',share:sharePreview._verifiedInput,action:'prerequisite_plan'} : sharePreview._verifiedInput)} className="btn-ghost w-full text-xs">
                  {sharePrerequisitesPending(sharePreview) ? (language === 'en' ? 'Review prerequisites in chat' : '在聊天中检查前置依赖') : '在聊天中继续生成安装计划'}
                </button>
              )}
            </div>
          )}
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Github size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">官方审核合集（Beta）</span>
          </div>
          <p className="text-xs leading-relaxed text-surface-500">
            输入 `ma-xxxxxx`、名称或标签，浏览由 ModAgent 审核并托管在 GitHub 的合集。选择后先核验，再生成安装计划。
          </p>
          <div className="flex gap-2">
            <input
              className="input-cyber text-xs"
              value={officialQuery}
              readOnly={officialBusy}
              onChange={event => {setOfficialQuery(event.target.value); setOfficialCatalog(null)}}
              onKeyDown={event => { if (event.key === 'Enter') loadOfficialCatalog() }}
              placeholder="例如 ma-263484、星露谷、新手"
            />
            <button type="button" disabled={officialBusy} onClick={loadOfficialCatalog} className="btn-ghost shrink-0 text-xs">
              浏览
            </button>
            <button type="button" disabled={officialBusy} onClick={diagnoseOfficialCatalogNetwork} className="btn-ghost shrink-0 text-xs" title="检查 GitHub Raw、Contents API、网页文件入口和本地缓存">
              网络诊断
            </button>
          </div>
          {officialCatalog && (
            <div className="space-y-2">
              {officialCatalog.collections?.length ? officialCatalog.collections.map(item => (
                <div key={item.id} className="rounded-lg border border-surface-600/80 bg-surface-900/45 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-white">{item.title || item.id}</p>
                      <p className="mt-1 text-[11px] text-cyber-cyan">{item.id} · {item.mod_count || 0} 个 Mod</p>
                    </div>
                    <button type="button" disabled={officialBusy} onClick={() => openOfficialCollection(item.id)} className="btn-ghost text-[11px] px-2 py-1">
                      打开
                    </button>
                  </div>
                  {item.description && <p className="mt-2 text-[11px] leading-relaxed text-surface-500">{item.description}</p>}
                  {item.warnings?.length > 0 && <p className="mt-2 text-[11px] text-cyber-yellow">注意：{item.warnings[0]}</p>}
                </div>
              )) : (
                <p className="rounded-lg border border-dashed border-surface-600 p-3 text-xs text-surface-500">
                  暂无匹配的官方合集。官方库上线并审核首批内容后会自动显示在这里。
                </p>
              )}
            </div>
          )}
          {sharePreview?.source_kind === 'official_collection' && sharePreview.items.length > 0 && (
            <button type="button" onClick={() => onStartSharePlan?.({ type: 'official', shareId: sharePreview.official.id,
              action:sharePrerequisitesPending(sharePreview) ? 'prerequisite_plan' : 'install_plan' })} className="btn-cyber w-full text-xs">
              {sharePrerequisitesPending(sharePreview) ? (language === 'en' ? 'Review prerequisites in chat' : '在聊天中检查前置依赖') : '在聊天中继续核验官方合集'}
            </button>
          )}
        </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Image size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">{language === 'en' ? 'Custom background' : '自定义背景'}</span>
          </div>
          {cfg.bg_error && <p role="alert" className="text-xs text-cyber-yellow">{ui('[BACKGROUND_READ_FAILED] 无法读取自定义背景，请检查背景目录权限。其他设置仍可使用；这不代表图片已被删除。', '[BACKGROUND_READ_FAILED] Cannot read the custom background. Check folder permissions. Other settings remain available; this does not mean your images were deleted.')}</p>}
          <p className="text-xs text-surface-500">{language === 'en' ? 'Choose a local JPG/PNG/GIF/WebP image up to 32 MiB. Older copies are kept until you remove custom backgrounds.' : '选择本地 JPG/PNG/GIF/WebP 图片，最大 32 MiB。旧副本保留至移除自定义背景时清理。'}</p>
          {bg ? (
            <div className="flex items-center gap-3">
              <img src={bgUrl || ''} className="w-24 h-16 rounded object-cover border border-surface-600" alt="bg preview" />
              <div className="flex gap-2">
                <button disabled={backgroundBusy} onClick={pickBg} className="btn-cyber text-xs">{language === 'en' ? 'Change background' : '更换'}</button>
                <button disabled={backgroundBusy} onClick={removeBg} className="btn-ghost text-xs text-cyber-red flex items-center gap-1"><Trash2 size={12} /> {language === 'en' ? 'Remove background' : '移除'}</button>
              </div>
            </div>
          ) : (
            <button disabled={backgroundBusy} onClick={pickBg} className="btn-cyber text-xs flex items-center gap-1.5 w-full justify-center h-16 border-dashed">
              <Image size={16} /> {language === 'en' ? 'Choose background image' : '选择背景图片'}
            </button>
          )}
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <RefreshCw size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">{language === 'en' ? 'App maintenance' : '应用维护'}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <button onClick={checkAppUpdate} disabled={checkingUpdate} className="btn-ghost flex items-center justify-center gap-1.5">
              <RefreshCw size={13} /> {checkingUpdate ? (language === 'en' ? 'Checking updates…' : '正在检查更新…') : (language === 'en' ? 'Check for updates' : '检查更新')}
            </button>
            <button disabled={maintenanceBusy} onClick={() => maintenanceAction('logs')} className="btn-ghost flex items-center justify-center gap-1.5">
              <FolderOpen size={13} /> {language === 'en' ? 'Open logs' : '运行日志'}
            </button>
            <button disabled={maintenanceBusy} onClick={() => maintenanceAction('copyLogs')} className="btn-ghost flex items-center justify-center gap-1.5">
              <Copy size={13} /> {language === 'en' ? 'Copy log folder path' : '复制日志路径'}
            </button>
            <button disabled={maintenanceBusy} onClick={() => maintenanceAction('data')} className="btn-ghost flex items-center justify-center gap-1.5">
              <FolderCog size={13} /> {language === 'en' ? 'Open configuration folder' : '打开配置目录'}
            </button>
            <button disabled={maintenanceBusy} onClick={() => maintenanceAction('cache')} className="btn-ghost flex items-center justify-center gap-1.5">
              <HardDrive size={13} /> {language === 'en' ? 'Open cache folder' : '打开缓存目录'}
            </button>
            <button onClick={exportDiagnostics} disabled={exportingDiagnostics} className="btn-ghost flex items-center justify-center gap-1.5">
              <FileDown size={13} /> {exportingDiagnostics ? (language === 'en' ? 'Finish the export dialog…' : '请完成导出窗口中的选择…') : (language === 'en' ? 'Export diagnostics' : '导出诊断')}
            </button>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Info size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">关于 {identity.productName}</span>
          </div>
          <div className="rounded-lg border border-surface-600/70 bg-surface-900/45 p-4">
            <p className="text-base font-semibold text-white">{identity.productName}</p>
            <p className="mt-1 text-xs text-surface-400">AI 驱动的开放式 Mod 管理助手</p>
            <p className="mt-3 text-[11px] text-surface-500">
              当前版本：v{identity.version || __MODAGENT_VERSION__} · {identity.channel === 'beta' ? 'Beta' : 'Stable'}
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button type="button" className="btn-ghost flex items-center justify-center gap-1.5"
              onClick={() => openProjectLink('https://github.com/millips/ModAgent')}>
              <Github size={13} /> GitHub
            </button>
            <button type="button" className="btn-ghost flex items-center justify-center gap-1.5"
              onClick={() => openProjectLink(`https://github.com/millips/ModAgent/releases/tag/v${identity.version || __MODAGENT_VERSION__}`)}>
              <BookOpen size={13} /> 更新日志
            </button>
            <button type="button" className="btn-ghost flex items-center justify-center gap-1.5"
              onClick={() => openProjectLink('https://github.com/millips/ModAgent-Share')}>
              <Globe size={13} /> 查看官方共享仓库
            </button>
            <button type="button" className="btn-ghost flex items-center justify-center gap-1.5"
              onClick={() => openLegalDocument('LICENSE.md')}>
              <Scale size={13} /> License
            </button>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Scale size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">关于与法律</span>
          </div>
          <p className="text-xs text-surface-500">
            查看隐私、第三方内容、P 会员规则、软件许可和依赖声明。购买或发布前请确认带“发行前填写”的运营信息已经补齐。
          </p>
          <div className="grid grid-cols-1 gap-2">
            {LEGAL_DOCUMENTS.map(item => (
              <button
                key={item.file}
                type="button"
                className="btn-ghost flex items-center gap-2 text-left"
                onClick={() => openLegalDocument(item.file)}
              >
                <FileText size={13} className="text-cyber-cyan" />
                <span>{item.label}</span>
              </button>
            ))}
          </div>
          <div className="text-[11px] text-surface-500 border-t border-surface-600/60 pt-2">
            {__MODAGENT_SUBSCRIPTION__ ? 'ModAgent P' : 'ModAgent'} v{__MODAGENT_VERSION__} · 发布者：ModAgent Project
          </div>
        </div>

        <button onClick={save} disabled={savingCredentials || saveRestartRequired} className="btn-cyber w-full">{saveRestartRequired ? (language === 'en' ? 'Restart to check saved state' : '请重启确认保存状态') : savingCredentials ? (language === 'en' ? 'Saving…' : '保存中…') : (language === 'en' ? 'Save settings' : '保存设置')}</button>
        </>}
      </div>
    </div>
  )
}
