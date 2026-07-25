import React, { useState } from 'react'
import { Zap, ArrowRight, ArrowLeft, ExternalLink } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'

const MODELS = [
  { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro（推荐）' },
  { value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash（更快）' },
  { value: 'gpt-4.1', label: 'OpenAI GPT（示例）' },
  { value: 'custom', label: '自定义模型名' },
]

const LLM_PROVIDERS = [
  {
    id: 'deepseek',
    label: 'DeepSeek（默认推荐）',
    endpoint: 'https://api.deepseek.com/v1',
    model: 'deepseek-v4-pro',
    keyLabel: 'LLM API Key',
    keyPlaceholder: '从 DeepSeek 开放平台获取',
    guideUrl: 'https://platform.deepseek.com/api_keys',
  },
  {
    id: 'openai',
    label: 'OpenAI / GPT',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-4.1',
    keyLabel: 'LLM API Key',
    keyPlaceholder: '填写 OpenAI API Key',
    guideUrl: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'custom',
    label: '自定义 OpenAI-Compatible',
    endpoint: '',
    model: '',
    keyLabel: 'LLM API Key',
    keyPlaceholder: '填写兼容 OpenAI Chat Completions 的 API Key',
    guideUrl: '',
  },
]

const KEY_GUIDES = [
  {
    id: 'nexus',
    label: 'Nexus Mods API Key',
    placeholder: '可跳过；需要 Nexus 下载/详情核验时再填写',
    url: 'https://www.nexusmods.com/users/myaccount?tab=api',
    optional: true,
  },
  {
    id: 'tavily',
    label: 'Tavily Search API Key',
    placeholder: '可跳过；用于增强跨站搜索',
    url: 'https://app.tavily.com/home',
    optional: true,
  },
  {
    id: 'llm',
    label: 'LLM API Key',
    placeholder: '至少填写一个大模型 API Key',
    url: '',
  },
]

export default function SetupPage({ onDone, api, toast }) {
  const [step, setStep] = useState(0)
  const [nexusKey, setNexusKey] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [customModel, setCustomModel] = useState('')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [saving, setSaving] = useState(false)

  const selectedProvider = LLM_PROVIDERS.find(item => item.id === provider) || LLM_PROVIDERS[0]
  const effectiveModel = model === 'custom' ? customModel.trim() : model.trim()
  const values = { nexus: nexusKey, tavily: tavilyKey, llm: llmKey }
  const setters = { nexus: setNexusKey, tavily: setTavilyKey, llm: setLlmKey }
  const llmKeyPresent = Boolean(llmKey.trim())
  const llmReady = llmKeyPresent && Boolean(endpoint.trim()) && Boolean(effectiveModel)

  const changeProvider = (nextProvider) => {
    const preset = LLM_PROVIDERS.find(item => item.id === nextProvider) || LLM_PROVIDERS[0]
    setProvider(preset.id)
    setEndpoint(preset.endpoint)
    setModel(preset.model || 'custom')
    setCustomModel(preset.model || '')
  }

  const openGuide = async (url) => {
    try {
      const result = await window.modagent?.openExternal?.(url)
      if (result?.error) throw new Error(result.error)
    } catch (_) {
      toast('无法打开 API Key 获取页面', 'error')
    }
  }

  const next = () => {
    if (!llmKeyPresent) {
      toast('请先填写一个 LLM API Key；Nexus 和 Tavily 可以稍后在设置里补', 'error')
      return
    }
    setStep(1)
  }

  const finish = async () => {
    if (saving) return
    if (!llmReady) {
      toast('请确认 LLM API Key、模型名和接口地址都已填写', 'error')
      return
    }
    setSaving(true)
    try {
      const secrets = {
        llm_api_key: llmKey.trim(),
      }
      if (nexusKey.trim()) secrets.nexus_api_key = nexusKey.trim()
      if (tavilyKey.trim()) secrets.tavily_api_key = tavilyKey.trim()
      const stored = await window.modagent?.saveSecrets?.(secrets)
      if (!stored?.ok) throw new Error('secure storage unavailable')

      const body = {
        llm_api_key: secrets.llm_api_key,
        llm_model: effectiveModel,
        llm_endpoint: endpoint.trim(),
      }
      if (secrets.nexus_api_key) body.api_key = secrets.nexus_api_key
      if (secrets.tavily_api_key) body.tavily_api_key = secrets.tavily_api_key

      const response = await fetch(api + '/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) throw new Error(`config failed: ${response.status}`)

      await fetch(api + '/chat/reset', { method: 'POST' })
      emitFeedback('success', { source: 'setup' })
      toast('配置已安全保存，正在扫描本机游戏')
      onDone()
    } catch (_) {
      emitFeedback('error', { source: 'setup' })
      toast('保存失败，请检查后端是否启动或稍后重试', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center justify-center flex-1 p-6">
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-8 w-[480px] max-h-[92vh] overflow-y-auto">
        <div className="flex items-center gap-2 mb-1">
          <Zap size={20} className="text-cyber-cyan" />
          <h2 className="text-lg font-bold text-white">ModAgent 首次配置</h2>
        </div>
        <p className="text-xs text-surface-500 mb-6">
          当前 v{__MODAGENT_VERSION__} 只要求配置一个大模型 API。DeepSeek 是默认推荐；Nexus 和 Tavily 均可跳过并稍后补充，已填写的 Key 会保存在本机 Windows 加密存储中。
        </p>

        {step === 0 && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-400 font-medium block mb-1">大模型服务商</label>
              <select className="input-cyber" value={provider} onChange={e => changeProvider(e.target.value)}>
                {LLM_PROVIDERS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </div>
            {KEY_GUIDES.map((item, index) => (
              <div key={item.id}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-surface-400 font-medium">
                    {item.id === 'llm' ? selectedProvider.keyLabel : item.label}
                    {item.optional && <span className="ml-1 text-[10px] text-surface-500">可选</span>}
                  </label>
                  {(item.id === 'llm' ? selectedProvider.guideUrl : item.url) && (
                    <button
                      type="button"
                      className="text-[11px] text-cyber-cyan hover:text-white flex items-center gap-1"
                      onClick={() => openGuide(item.id === 'llm' ? selectedProvider.guideUrl : item.url)}
                    >
                      获取 Key <ExternalLink size={11} />
                    </button>
                  )}
                </div>
                <input
                  type="password"
                  className="input-cyber"
                  placeholder={item.id === 'llm' ? selectedProvider.keyPlaceholder : item.placeholder}
                  value={values[item.id]}
                  onChange={e => setters[item.id](e.target.value)}
                  autoFocus={index === 2}
                />
              </div>
            ))}
            <p className="text-[11px] leading-relaxed text-surface-500">
              LLM 用于中文对话、推荐和安装计划；Nexus 用于读取和下载 Nexus Mods；Tavily 用于增强跨网站搜索。当前支持 OpenAI-compatible 接口，原生 Claude/Gemini 等专用协议会放到后续版本。
            </p>
            <button onClick={next} className="btn-cyber w-full flex items-center justify-center gap-2 mt-2">
              下一步 <ArrowRight size={14} />
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">模型</label>
              <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
                {MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            {model === 'custom' && (
              <div>
                <label className="text-xs text-surface-500 block mb-1 font-medium">自定义模型名</label>
                <input
                  className="input-cyber"
                  value={customModel}
                  onChange={e => setCustomModel(e.target.value)}
                  placeholder="例如服务商文档中的模型 ID"
                />
              </div>
            )}
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">接口地址</label>
              <input
                className="input-cyber"
                value={endpoint}
                onChange={e => setEndpoint(e.target.value)}
                placeholder="https://.../v1"
              />
            </div>
            <div className="rounded-lg border border-surface-600 bg-surface-900/60 p-3 text-xs text-surface-400">
              完成后 ModAgent 会自动扫描 Steam 游戏。进入主界面后选择游戏，即可开始聊天、搜索和安装 Mod。
            </div>
            <div className="flex gap-2 mt-2">
              <button onClick={() => setStep(0)} className="btn-ghost flex items-center justify-center gap-1 flex-1">
                <ArrowLeft size={14} /> 上一步
              </button>
              <button
                onClick={finish}
                disabled={saving}
                className="btn-cyber flex items-center justify-center gap-2 flex-1 disabled:opacity-50"
              >
                <Zap size={14} /> {saving ? '保存中…' : '保存并进入'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
