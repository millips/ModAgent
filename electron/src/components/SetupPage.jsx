import React, { useState } from 'react'
import { Zap, ArrowRight, ArrowLeft, ExternalLink } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'

const MODELS = [
  { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro（推荐）' },
  { value: 'deepseek-chat', label: 'DeepSeek Chat' },
  { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
]

const KEY_GUIDES = [
  {
    id: 'nexus',
    label: 'Nexus Mods API Key',
    placeholder: '从 Nexus Mods 个人设置获取',
    url: 'https://www.nexusmods.com/users/myaccount?tab=api',
  },
  {
    id: 'tavily',
    label: 'Tavily Search API Key',
    placeholder: '从 Tavily 控制台获取',
    url: 'https://app.tavily.com/home',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek API Key',
    placeholder: '从 DeepSeek 开放平台获取',
    url: 'https://platform.deepseek.com/api_keys',
  },
]

export default function SetupPage({ onDone, api, toast }) {
  const [step, setStep] = useState(0)
  const [nexusKey, setNexusKey] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [saving, setSaving] = useState(false)

  const values = { nexus: nexusKey, tavily: tavilyKey, deepseek: llmKey }
  const setters = { nexus: setNexusKey, tavily: setTavilyKey, deepseek: setLlmKey }
  const allKeysPresent = nexusKey.trim() && tavilyKey.trim() && llmKey.trim()

  const openGuide = async (url) => {
    try {
      const result = await window.modagent?.openExternal?.(url)
      if (result?.error) throw new Error(result.error)
    } catch (_) {
      toast('无法打开 API Key 获取页面', 'error')
    }
  }

  const next = () => {
    if (!allKeysPresent) {
      toast('请填写 Nexus、Tavily 和 DeepSeek 三个 API Key', 'error')
      return
    }
    setStep(1)
  }

  const finish = async () => {
    if (!allKeysPresent || saving) return
    setSaving(true)
    try {
      const secrets = {
        nexus_api_key: nexusKey.trim(),
        tavily_api_key: tavilyKey.trim(),
        llm_api_key: llmKey.trim(),
      }
      const stored = await window.modagent?.saveSecrets?.(secrets)
      if (!stored?.ok) throw new Error('secure storage unavailable')

      const response = await fetch(api + '/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: secrets.nexus_api_key,
          tavily_api_key: secrets.tavily_api_key,
          llm_api_key: secrets.llm_api_key,
          llm_model: model,
          llm_endpoint: endpoint.trim(),
        }),
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
          当前 v1.0 面向中文用户并正式支持 DeepSeek。三个 Key 均保存在本机 Windows 加密存储中。
        </p>

        {step === 0 && (
          <div className="space-y-4">
            {KEY_GUIDES.map((item, index) => (
              <div key={item.id}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-surface-400 font-medium">{item.label}</label>
                  <button
                    type="button"
                    className="text-[11px] text-cyber-cyan hover:text-white flex items-center gap-1"
                    onClick={() => openGuide(item.url)}
                  >
                    获取 Key <ExternalLink size={11} />
                  </button>
                </div>
                <input
                  type="password"
                  className="input-cyber"
                  placeholder={item.placeholder}
                  value={values[item.id]}
                  onChange={e => setters[item.id](e.target.value)}
                  autoFocus={index === 0}
                />
              </div>
            ))}
            <p className="text-[11px] leading-relaxed text-surface-500">
              Nexus 用于读取和下载 Nexus Mods；Tavily 用于跨网站搜索；DeepSeek 用于中文对话、推荐和安装计划。
            </p>
            <button onClick={next} className="btn-cyber w-full flex items-center justify-center gap-2 mt-2">
              下一步 <ArrowRight size={14} />
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">DeepSeek 模型</label>
              <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
                {MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">DeepSeek 接口地址</label>
              <input className="input-cyber" value={endpoint} onChange={e => setEndpoint(e.target.value)} />
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
