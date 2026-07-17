import React, { useState } from 'react'
import { Key, Cpu, Zap, ArrowRight, ArrowLeft } from 'lucide-react'

const MODELS = [
  { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro (推荐)' },
  { value: 'deepseek-chat', label: 'DeepSeek V3 (快速)' },
  { value: 'deepseek-reasoner', label: 'DeepSeek R1 (推理)' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
]

export default function SetupPage({ onDone, api, toast }) {
  const [step, setStep] = useState(0)
  const [nexusKey, setNexusKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')

  const finish = async () => {
    if (!nexusKey.trim() || !llmKey.trim()) {
      toast('请填写所有 API Key', 'error')
      return
    }
    try {
      await fetch(api + '/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: nexusKey.trim(),
          llm_api_key: llmKey.trim(),
          llm_model: model,
          llm_endpoint: endpoint.trim(),
        }),
      })
      await fetch(api + '/chat/reset', { method: 'POST' })
      toast('配置完成！')
      onDone()
    } catch (_) {
      toast('保存失败，请检查后端是否启动', 'error')
    }
  }

  return (
    <div className="flex items-center justify-center flex-1">
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-8 w-[440px]">
        <div className="flex items-center gap-2 mb-1">
          <Zap size={20} className="text-cyber-cyan" />
          <h2 className="text-lg font-bold text-white">ModAgent 配置</h2>
        </div>
        <p className="text-xs text-surface-500 mb-6">首次使用，请设置 API 密钥。之后可在设置中修改。</p>

        {step === 0 && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">Nexus Mods API Key</label>
              <input type="password" className="input-cyber" placeholder="从 nexusmods.com 个人设置获取"
                value={nexusKey} onChange={e => setNexusKey(e.target.value)} autoFocus />
            </div>
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">LLM API Key (DeepSeek)</label>
              <input type="password" className="input-cyber" placeholder="从 platform.deepseek.com 获取"
                value={llmKey} onChange={e => setLlmKey(e.target.value)} />
            </div>
            <button onClick={() => setStep(1)} className="btn-cyber w-full flex items-center justify-center gap-2 mt-2">
              下一步 <ArrowRight size={14} />
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">选择模型</label>
              <select className="input-cyber" value={model} onChange={e => setModel(e.target.value)}>
                {MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-surface-500 block mb-1 font-medium">接口地址</label>
              <input className="input-cyber" value={endpoint} onChange={e => setEndpoint(e.target.value)} />
            </div>
            <div className="flex gap-2 mt-2">
              <button onClick={() => setStep(0)} className="btn-ghost flex items-center justify-center gap-1 flex-1">
                <ArrowLeft size={14} /> 上一步
              </button>
              <button onClick={finish} className="btn-cyber flex items-center justify-center gap-2 flex-1">
                <Zap size={14} /> 完成配置
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
