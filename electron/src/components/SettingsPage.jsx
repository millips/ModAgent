import React, { useState, useEffect } from 'react'
import { Key, Cpu, HardDrive, Globe, Image, Trash2, FolderOpen, FileDown, RefreshCw, Scale, FileText } from 'lucide-react'
import defaultWallpaper from '../assets/default-wallpaper.png'

const LEGAL_DOCUMENTS = [
  { file: 'PRIVACY.md', label: '\u9690\u79c1\u8bf4\u660e' },
  { file: 'THIRD-PARTY-MODS-DISCLAIMER.md', label: '\u7b2c\u4e09\u65b9 Mod \u4e0e\u7f51\u7ad9\u514d\u8d23\u58f0\u660e' },
  { file: 'LICENSE.md', label: '\u5f00\u6e90\u8bb8\u53ef\u8bf4\u660e' },
  { file: 'THIRD_PARTY_NOTICES.md', label: '\u7b2c\u4e09\u65b9\u8f6f\u4ef6\u58f0\u660e' },
]

export default function SettingsPage({ toast, api }) {
  const [cfg, setCfg] = useState({})
  const [nexusKey, setNexusKey] = useState('')
  const [llmKey, setLlmKey] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [model, setModel] = useState('deepseek-v4-pro')
  const [endpoint, setEndpoint] = useState('https://api.deepseek.com/v1')
  const [bg, setBg] = useState(null)
  const [bgUrl, setBgUrl] = useState(defaultWallpaper)

  useEffect(() => {
    fetch(api + '/status').then(r => r.json()).then(s => {
      setCfg(s)
      setModel(s.llm_model || 'deepseek-v4-pro')
      setEndpoint(s.llm_endpoint || 'https://api.deepseek.com/v1')
      setBg(s.bg || null)
      if (s.bg) window.modagent.getBgDataUrl(s.bg).then(setBgUrl).catch(() => setBgUrl(defaultWallpaper))
      else setBgUrl(defaultWallpaper)
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
        document.body.classList.remove('default-bg')
        document.body.style.backgroundImage = dataUrl ? `url("${dataUrl}")` : ''
        toast('背景已更新')
      }
    } catch (_) { toast('选择失败', 'error') }
  }

  const removeBg = async () => {
    try {
      await window.modagent.removeBg()
      setBg(null)
      setBgUrl(defaultWallpaper)
      document.body.classList.add('has-bg', 'default-bg')
      document.body.style.backgroundImage = `url("${defaultWallpaper}")`
      toast('已恢复默认背景')
    } catch (_) { toast('移除失败', 'error') }
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
      toast('\u65e0\u6cd5\u6253\u5f00\u6cd5\u5f8b\u6587\u4ef6\uff0c\u8bf7\u91cd\u65b0\u5b89\u88c5\u6216\u68c0\u67e5\u53d1\u884c\u5305\u5b8c\u6574\u6027', 'error')
    }
  }

  const save = async () => {
    const body = { llm_model: model, llm_endpoint: endpoint }
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
            <label className="text-xs text-surface-500 block mb-1">Nexus Mods API Key</label>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.api_key_set ? '已设置' : '未设置'}
              value={nexusKey}
              onChange={e => setNexusKey(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">Tavily Search API Key</label>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.tavily_set ? '已设置' : '未设置 (可选，提升搜索质量)'}
              value={tavilyKey}
              onChange={e => setTavilyKey(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-surface-500 block mb-1">LLM API Key</label>
            <input
              type="password"
              className="input-cyber"
              placeholder={cfg.llm_set ? '已设置' : '未设置'}
              value={llmKey}
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
              <option value="gpt-4o">GPT-4o</option>
              <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
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
            <div className="flex items-center gap-3">
              <img src={defaultWallpaper} className="w-24 h-16 rounded object-cover border border-surface-600" alt="默认背景预览" />
              <div>
                <p className="text-xs text-surface-400 mb-2">当前使用默认背景</p>
                <button onClick={pickBg} className="btn-cyber text-xs flex items-center gap-1.5">
                  <Image size={14} /> 选择自定义图片
                </button>
              </div>
            </div>
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
            <span className="text-sm font-medium">{'\u5173\u4e8e\u4e0e\u6cd5\u5f8b'}</span>
          </div>
          <p className="text-xs text-surface-500">
            {'\u67e5\u770b\u9690\u79c1\u3001\u7b2c\u4e09\u65b9 Mod \u98ce\u9669\u3001\u5f00\u6e90\u8bb8\u53ef\u548c\u4f9d\u8d56\u58f0\u660e\u3002'}
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
            ModAgent v1.0.0 {'\u00b7 \u53d1\u5e03\u8005\uff1aModAgent Project'}
          </div>
        </div>

        <button onClick={save} className="btn-cyber w-full">保存设置</button>
      </div>
    </div>
  )
}
