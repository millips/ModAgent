import React, { useState, useRef } from 'react'
import { Zap } from 'lucide-react'
import { emitFeedback } from '../feedback/feedbackBus'
import { LANGUAGES, tr } from '../i18n'
import { saveSetupConfiguration, setupFailureMessage } from '../setupWorkflow.mjs'
import {CredentialHelp} from './CredentialGuide'

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
    id: 'llm',
    label: 'LLM API Key',
    placeholder: '至少填写一个大模型 API Key',
    url: '',
  },
]

export default function SetupPage({ onDone, api, toast, language = 'zh-CN', onLanguageChange }) {
  const [llmKey, setLlmKey] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [customModel, setCustomModel] = useState('')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [saving, setSaving] = useState(false)
  const [restartRequired, setRestartRequired] = useState(false)
  const savingRef = useRef(false)

  const selectedProvider = LLM_PROVIDERS.find(item => item.id === provider) || LLM_PROVIDERS[0]
  const effectiveModel = model === 'custom' ? customModel.trim() : model.trim()
  const values = { llm: llmKey }
  const setters = { llm: setLlmKey }
  const llmKeyPresent = Boolean(llmKey.trim())
  const llmReady = llmKeyPresent && Boolean(endpoint.trim()) && Boolean(effectiveModel)

  const changeProvider = (nextProvider) => {
    const preset = LLM_PROVIDERS.find(item => item.id === nextProvider) || LLM_PROVIDERS[0]
    setProvider(preset.id)
    setLlmKey('')
    setEndpoint(preset.endpoint)
    setModel(preset.model || 'custom')
    setCustomModel(preset.model || '')
  }

  const finish = async () => {
    if (savingRef.current || restartRequired) return
    if (!llmReady) {
      toast(language==='en'?'Enter an LLM key, model and endpoint.':'请确认 LLM API Key、模型名和接口地址都已填写', 'error')
      return
    }
    setSaving(true)
    savingRef.current = true
    try {
      const secrets = {
        llm_api_key: llmKey.trim(),
      }
      const body = {
        llm_api_key: secrets.llm_api_key,
        llm_model: effectiveModel,
        llm_endpoint: endpoint.trim(),
        language,
      }
      await saveSetupConfiguration(api, body, {store:window.modagent?.saveSecrets})
      // /chat/reset without a session ID is a backend no-op; do not add a
      // second network dependency after configuration was already saved.
      emitFeedback('success', { source: 'setup' })
      toast(language === 'en' ? 'Configuration saved. Detecting local games.' : '配置已安全保存，正在扫描本机游戏')
      onDone()
    } catch (error) {
      emitFeedback('error', { source: 'setup' })
      if (error.restartRequired) setRestartRequired(true)
      toast(setupFailureMessage(error, language), 'error')
    } finally {
      setSaving(false)
      savingRef.current = false
    }
  }

  return (
    <div className="flex items-center justify-center flex-1 p-6">
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-8 w-[480px] max-h-[92vh] overflow-y-auto">
        <div className="flex items-center gap-2 mb-1">
          <Zap size={20} className="text-cyber-cyan" />
          <h2 className="text-lg font-bold text-white">{tr(language, 'setupTitle')}</h2>
        </div>
        <p className="text-xs text-surface-500 mb-6">
          {language==='en'?'Start with one AI API key. Connect Mod sources later, only when needed.':'只需一个大模型 API Key 即可进入。其他来源用到时再配置，不必现在注册。'}
        </p>

          <fieldset disabled={saving||restartRequired} className="space-y-4">
            <div>
              <label className="text-xs text-surface-400 font-medium block mb-1">{tr(language, 'language')}</label>
              <select className="input-cyber" value={language} onChange={e => onLanguageChange?.(e.target.value)}>
                {LANGUAGES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <p className="mt-1 text-[11px] text-surface-500">{tr(language, 'languageHelp')}</p>
            </div>
            <div>
              <label className="text-xs text-surface-400 font-medium block mb-1">{tr(language, 'provider')}</label>
              <select className="input-cyber" value={provider} onChange={e => changeProvider(e.target.value)}>
                {LLM_PROVIDERS.map(item => <option key={item.id} value={item.id}>{language==='en'?({deepseek:'DeepSeek (default)',openai:'OpenAI / GPT',custom:'Custom compatible API'})[item.id]:item.label}</option>)}
              </select>
            </div>
            {KEY_GUIDES.map((item, index) => (
              <div key={item.id}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-surface-400 font-medium">
                    {item.id === 'llm' ? selectedProvider.keyLabel : item.label}
                    {item.optional && <span className="ml-1 text-[10px] text-surface-500">{tr(language, 'optional')}</span>}
                  </label>
                </div>
                <input
                  type="password"
                  className="input-cyber"
                  aria-label="LLM API Key"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={language==='en'?'Paste your API key':selectedProvider.keyPlaceholder}
                  value={values[item.id]}
                  onChange={e => setters[item.id](e.target.value)}
                  autoFocus={index === 0}
                />
              </div>
            ))}
            <CredentialHelp provider={provider} language={language} toast={toast}/>
            <p className="text-[11px] text-surface-400">{language==='en'?'Saving does not verify the provider connection. Never paste keys into chat.':'保存不代表已通过服务商连接验证。请勿把密钥发到聊天里。'}</p>

          <details open={provider==='custom'} className="space-y-4">
            <summary className="cursor-pointer text-xs text-surface-400">{language==='en'?'Advanced: model and endpoint (presets filled in)':'高级：模型和接口地址（已自动填写）'}</summary>
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">{tr(language, 'model')}</label>
              <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
                {MODELS.map(m => <option key={m.value} value={m.value}>{language==='en'?(m.value==='custom'?'Custom model ID':m.value):m.label}</option>)}
              </select>
            </div>
            {model === 'custom' && (
              <div>
                <label className="text-xs text-surface-500 block mb-1 font-medium">{tr(language, 'customModel')}</label>
                <input
                  className="input-cyber"
                  value={customModel}
                  onChange={e => setCustomModel(e.target.value)}
                  placeholder={language==='en'?'Model ID from your provider':'例如服务商文档中的模型 ID'}
                />
              </div>
            )}
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">{tr(language, 'endpoint')}</label>
              <input
                className="input-cyber"
                value={endpoint}
                onChange={e => setEndpoint(e.target.value)}
                placeholder="https://.../v1"
              />
            </div>
            <div className="rounded-lg border border-surface-600 bg-surface-900/60 p-3 text-xs text-surface-400">
              {tr(language, 'setupDetail')}
            </div>
          </details>
            <div className="flex gap-2 mt-2">
              <button
                onClick={finish}
                disabled={saving || restartRequired || !llmReady}
                className="btn-cyber flex items-center justify-center gap-2 flex-1 disabled:opacity-50"
              >
                <Zap size={14} /> {restartRequired ? (language === 'en' ? 'Restart to verify save' : '请重启确认保存状态') : saving ? tr(language, 'saving') : tr(language, 'saveAndEnter')}
              </button>
            </div>
          </fieldset>
      </div>
    </div>
  )
}
