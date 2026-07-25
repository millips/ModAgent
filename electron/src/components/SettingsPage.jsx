import React, { useState, useEffect } from 'react'
import { Key, Cpu, Globe, Image, Trash2, FolderOpen, FileDown, RefreshCw, Scale, FileText, PanelLeft } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { SettingsEditionPanel, applyEditionDefaultBackground } from '@edition'
import {
  readLayoutPreference,
  saveLayoutPreference,
} from '../theme/layoutPreference'

const COMMON_LEGAL_DOCUMENTS = [
  { file: 'PRIVACY.md', label: '隐私说明' },
  { file: 'THIRD-PARTY-MODS-DISCLAIMER.md', label: '第三方 Mod 与网站免责声明' },
  { file: 'THIRD_PARTY_NOTICES.md', label: '第三方软件声明' },
]
const SUBSCRIPTION_LEGAL_DOCUMENTS = [
  { file: 'SUBSCRIPTION-REFUND-SUPPORT.md', label: '订阅、退款与支持说明' },
  { file: 'SUBSCRIPTION-SOFTWARE-LICENSE.md', label: '订阅版软件许可' },
  { file: 'PROPRIETARY-ASSETS-LICENSE.md', label: '订阅素材许可' },
]
const LEGAL_DOCUMENTS = __MODAGENT_SUBSCRIPTION__
  ? [...COMMON_LEGAL_DOCUMENTS, ...SUBSCRIPTION_LEGAL_DOCUMENTS]
  : COMMON_LEGAL_DOCUMENTS

export default function SettingsPage({ toast, api }) {
  const [cfg, setCfg] = useState({})
  const [nexusKey, setNexusKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [editingKeys, setEditingKeys] = useState({
    nexus: false, tavily: false, llm: false,
  })
  const [model, setModel] = useState('deepseek-v4-pro')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [recommendationLimit, setRecommendationLimit] = useState(10)
  const [layoutMode, setLayoutMode] = useState(readLayoutPreference)
  const [bg, setBg] = useState(null)
  const [bgUrl, setBgUrl] = useState(null)

  useEffect(() => {
    fetch(api + '/status').then(r => r.json()).then(s => {
      setCfg(s)
      setModel(s.llm_model || 'deepseek-v4-pro')
      setEndpoint(s.llm_endpoint || 'https://api.deepseek.com/v1')
      setRecommendationLimit(Math.max(2, Math.min(Number(s.recommendation_limit) || 10, 20)))
      setBg(s.bg || null)
      if (s.bg) window.modagent.getBgDataUrl(s.bg).then(setBgUrl).catch(() => {})
    }).catch(() => {})
  }, [])

  const pickBg = async () => {
    try {
      const name = await window.modagent.selectBg()
      if (name) {
        const dataUrl = await window.modagent.getBgDataUrl(name)
        setBg(name)
        setBgUrl(dataUrl)
        document.body.classList.add('has-bg')
        document.body.style.backgroundImage = dataUrl ? `url("${dataUrl}")` : ''
        emitFeedback('notice', { source: 'background' })
        toast('背景已更新')
      }
    } catch (_) { emitFeedback('error', { source: 'background' }); toast('选择失败', 'error') }
  }

  const removeBg = async () => {
    try {
      await window.modagent.removeBg()
      setBg(null)
      setBgUrl(null)
      applyEditionDefaultBackground()
      emitFeedback('remove-complete', { source: 'background' })
      toast('背景已移除')
    } catch (_) { emitFeedback('error', { source: 'background' }); toast('移除失败', 'error') }
  }


  const checkAppUpdate = async () => {
    try {
      const result = await window.modagent?.checkForAppUpdate?.()
      if (!result) throw new Error('unavailable')
      toast(result.ok ? `\u5df2\u68c0\u67e5\u66f4\u65b0\uff1a${result.version || '\u5f53\u524d\u5df2\u662f\u6700\u65b0\u7248'}` : `\u66f4\u65b0\u68c0\u67e5\u5931\u8d25\uff1a${result.error || '\u672a\u77e5\u9519\u8bef'}`, result.ok ? 'info' : 'error')
    } catch (_) {
      toast('\u66f4\u65b0\u68c0\u67e5\u4ec5\u5728\u6b63\u5f0f\u5b89\u88c5\u7248\u4e2d\u53ef\u7528', 'error')
    }
  }

  const openDiagnostics = async () => {
    try { await window.modagent?.openDiagnosticsFolder?.() }
    catch (_) { toast('\u65e0\u6cd5\u6253\u5f00\u8fd0\u884c\u65e5\u5fd7', 'error') }
  }

  const exportDiagnostics = async () => {
    try {
      const output = await window.modagent?.exportRuntimeDiagnostics?.()
      if (output) toast('\u8bca\u65ad\u4fe1\u606f\u5df2\u5bfc\u51fa')
    } catch (_) { toast('\u8bca\u65ad\u4fe1\u606f\u5bfc\u51fa\u5931\u8d25', 'error') }
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
    const body = {
      llm_model: model,
      llm_endpoint: endpoint,
      recommendation_limit: Math.max(2, Math.min(Number(recommendationLimit) || 10, 20)),
    }
    const secrets = {}
    if (nexusKey && nexusKey !== '********') { body.api_key = nexusKey; secrets.nexus_api_key = nexusKey }
    if (llmKey && llmKey !== '********') { body.llm_api_key = llmKey; secrets.llm_api_key = llmKey }
    if (tavilyKey && tavilyKey !== '********') { body.tavily_api_key = tavilyKey; secrets.tavily_api_key = tavilyKey }
    if (Object.keys(secrets).length && window.modagent?.saveSecrets) {
      await window.modagent.saveSecrets(secrets)
    }
    await fetch(api + '/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    await fetch(api + '/chat/reset', { method: 'POST' })
    setCfg(prev => ({
      ...prev,
      api_key_set: prev.api_key_set || Boolean(nexusKey),
      tavily_set: prev.tavily_set || Boolean(tavilyKey),
      llm_set: prev.llm_set || Boolean(llmKey),
    }))
    setNexusKey('')
    setTavilyKey('')
    setLlmKey('')
    setEditingKeys({ nexus: false, tavily: false, llm: false })
    emitFeedback('success', { source: 'settings' })
    toast('设置已保存')
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center px-4 py-3 border-b border-surface-600">
        <h2 className="text-base font-semibold flex items-center gap-2">
          <Cpu size={16} className="text-cyber-cyan" /> 设置
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto p-6 max-w-lg space-y-5">
        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Key size={14} className="text-cyber-yellow" />
            <span className="text-sm font-medium">API 密钥</span>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">Nexus Mods API Key</label>
              {cfg.api_key_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setNexusKey(''); setEditingKeys(v => ({ ...v, nexus: true })) }}>
                <RefreshCw size={11} /> 重新输入
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.api_key_set ? '已设置' : '未设置'}
              value={nexusKey}
              disabled={cfg.api_key_set && !editingKeys.nexus}
              onChange={e => setNexusKey(e.target.value)}
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">Tavily Search API Key</label>
              {cfg.tavily_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setTavilyKey(''); setEditingKeys(v => ({ ...v, tavily: true })) }}>
                <RefreshCw size={11} /> 重新输入
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.tavily_set ? '已设置' : '未设置（完整跨站搜索所需）'}
              value={tavilyKey}
              disabled={cfg.tavily_set && !editingKeys.tavily}
              onChange={e => setTavilyKey(e.target.value)}
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-surface-500">LLM API Key</label>
              {cfg.llm_set && <button className="btn-ghost text-[11px] py-1 px-2 flex items-center gap-1"
                onClick={() => { setLlmKey(''); setEditingKeys(v => ({ ...v, llm: true })) }}>
                <RefreshCw size={11} /> 重新输入
              </button>}
            </div>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.llm_set ? '已设置' : '未设置'}
              value={llmKey}
              disabled={cfg.llm_set && !editingKeys.llm}
              onChange={e => setLlmKey(e.target.value)}
            />
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Cpu size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">模型设置</span>
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">模型</label>
            <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              <option value="deepseek-chat">DeepSeek V3</option>
              <option value="deepseek-reasoner">DeepSeek R1</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">接口地址</label>
            <div className="flex items-center gap-2">
              <Globe size={14} className="text-surface-500" />
              <input className="input-cyber" value={endpoint} onChange={e => setEndpoint(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Cpu size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">智能推荐</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <label htmlFor="recommendation-limit" className="text-xs text-surface-400">
                最大候选数
              </label>
              <p className="mt-1 text-[11px] leading-relaxed text-surface-500">
                默认 10 个，可设置为 2–20 个；实际数量取决于本轮有效搜索结果。
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
            <span className="text-sm font-medium">界面布局</span>
          </div>
          <p className="text-xs leading-relaxed text-surface-500">
            只调整区域比例、留白和分区轮廓，不改变按钮含义与操作流程。
          </p>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="界面布局">
            {[
              ['plain', '朴素版', '规整矩形与均衡间距'],
              ['designed', '设计版', '黄金比例与非对称分区'],
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
                  toast(`已切换为${label}`)
                }}
              >
                <span className="block text-xs font-medium text-white">{label}</span>
                <span className="mt-1 block text-[10px] leading-relaxed text-surface-500">{note}</span>
              </button>
            ))}
          </div>
        </div>

        <SettingsEditionPanel toast={toast} />

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2 mb-1">
            <Image size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">自定义背景</span>
          </div>
          <p className="text-xs text-surface-500">选择本地图片作为应用背景。支持 JPG/PNG/GIF/WebP。</p>
          {bg ? (
            <div className="flex items-center gap-3">
              <img src={bgUrl || ''} className="w-24 h-16 rounded object-cover border border-surface-600" alt="bg preview" />
              <div className="flex gap-2">
                <button onClick={pickBg} className="btn-cyber text-xs">更换</button>
                <button onClick={removeBg} className="btn-ghost text-xs text-cyber-red flex items-center gap-1"><Trash2 size={12} /> 移除</button>
              </div>
            </div>
          ) : (
            <button onClick={pickBg} className="btn-cyber text-xs flex items-center gap-1.5 w-full justify-center h-16 border-dashed">
              <Image size={16} /> 选择背景图片
            </button>
          )}
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <RefreshCw size={14} className="text-cyber-cyan" />
            <span className="text-sm font-medium">{`\u5e94\u7528\u7ef4\u62a4`}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <button onClick={checkAppUpdate} className="btn-ghost flex items-center justify-center gap-1.5">
              <RefreshCw size={13} /> {`\u68c0\u67e5\u66f4\u65b0`}
            </button>
            <button onClick={openDiagnostics} className="btn-ghost flex items-center justify-center gap-1.5">
              <FolderOpen size={13} /> {`\u8fd0\u884c\u65e5\u5fd7`}
            </button>
            <button onClick={exportDiagnostics} className="btn-ghost flex items-center justify-center gap-1.5">
              <FileDown size={13} /> {`\u5bfc\u51fa\u8bca\u65ad`}
            </button>
          </div>
        </div>

        <div className="card-cyber space-y-3">
          <div className="flex items-center gap-2">
            <Scale size={14} className="text-cyber-purple" />
            <span className="text-sm font-medium">关于与法律</span>
          </div>
          <p className="text-xs text-surface-500">
            查看隐私、第三方内容、订阅规则、软件许可和依赖声明。购买或发布前请确认带“发行前填写”的运营信息已经补齐。
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
            {__MODAGENT_SUBSCRIPTION__ ? 'ModAgent Pro' : 'ModAgent'} v{__MODAGENT_VERSION__} · 发布者：ModAgent Project
          </div>
        </div>

        <button onClick={save} className="btn-cyber w-full">保存设置</button>
      </div>
    </div>
  )
}
