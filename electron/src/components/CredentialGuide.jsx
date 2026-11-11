import React, {useRef, useState} from 'react'
import {saveSetupConfiguration, setupFailureMessage} from '../setupWorkflow.mjs'

const GUIDES = {
  nexus: {name:'Nexus Mods', url:'https://www.nexusmods.com/users/myaccount?tab=api',
    zh:'登录 Nexus → 在 API 页面创建或查看个人 Key → 复制并粘贴。Key 用于文件核验；普通账号网页下载仍可能需要在 ModAgent 浏览器中登录。',
    en:'Sign in to Nexus → create or view your personal key on the API page → copy and paste it. The key verifies file metadata; website downloads may still require signing in through the ModAgent browser.'},
  tavily: {name:'Tavily', url:'https://app.tavily.com/home',
    zh:'注册或登录 → 在控制台找到 API Keys → 复制 Key。用于增强跨站搜索；来源明确的分享合集通常不需要。额度和网络限制仍适用。',
    en:'Sign up or sign in → find API Keys in the dashboard → copy your key. Optional cross-site search enhancement; collections with known sources usually do not need it. Usage and network limits still apply.'},
  deepseek: {name:'DeepSeek', url:'https://platform.deepseek.com/api_keys',
    zh:'注册或登录开放平台 → 创建 API Key → 复制并粘贴。请确认 API 账户有可用额度，必要时充值；网页登录不代替 API Key。',
    en:'Sign up or sign in to the API platform → create an API key → copy and paste it. Check your API balance or credits; top up if needed. Website login does not replace an API key.'},
  openai: {name:'OpenAI', url:'https://platform.openai.com/api-keys',
    zh:'登录 API 平台 → 在 API Keys 页面创建密钥 → 复制并粘贴。请确认 API 账户和所选模型可用。',
    en:'Sign in to the API platform → create a key on the API Keys page → copy and paste it. Check API account and model availability.'},
}

export function CredentialHelp({provider, language='zh-CN', toast=()=>{}}) {
  const guide=GUIDES[provider], en=language==='en'
  if(!guide)return <p className="text-xs text-surface-400">{en?'Get the API key, endpoint and model ID from your provider.':'请从所选服务商获取 API Key、接口地址和模型 ID。'}</p>
  const open=async()=>{
    try {
      const result=await window.modagent?.openExternal?.(guide.url)
      if(result?.ok!==true)throw Error('guide_open_failed')
    } catch {toast(en?'Could not open the page. Use the address shown below.':'未能打开网页，请复制下方地址到浏览器。','error')}
  }
  return <div className="text-xs leading-relaxed text-surface-400 space-y-1" data-credential-help={provider}>
    <p>{en?guide.en:guide.zh}</p>
    <button type="button" className="text-cyber-cyan hover:underline" onClick={open}>{en?`Open ${guide.name} API key page ↗`:`直达 ${guide.name} 密钥页面 ↗`}</button>
    <p className="break-all select-text text-[10px]">{guide.url}</p>
    <p>{en?'After signing in, use this link again if the site did not return to the key page.':'登录后如果没有返回密钥页，再点一次上方链接即可。'}</p>
  </div>
}

export default function CredentialGuide({provider,api,language='zh-CN',toast,onClose,onSaved}) {
  const en=language==='en', [key,setKey]=useState(''), [busy,setBusy]=useState(false)
  const [restart,setRestart]=useState(false), [saved,setSaved]=useState(false), lock=useRef(false)
  if(!['nexus','tavily'].includes(provider))return null
  const save=async()=>{
    if(lock.current||restart||!key.trim())return
    lock.current=true;setBusy(true)
    try {
      if(typeof window.modagent?.saveSecrets!=='function')throw {stage:'credentials',cause:new Error('credential_encryption_unavailable')}
      await saveSetupConfiguration(api,{[provider==='nexus'?'nexus_api_key':'tavily_api_key']:key.trim()},{store:window.modagent.saveSecrets})
      setKey('');setSaved(true);onSaved?.(provider)
    } catch(error) {
      if(error.restartRequired)setRestart(true)
      toast(setupFailureMessage(error,language),'error')
    } finally {lock.current=false;setBusy(false)}
  }
  return <section role="region" aria-label={en?'Secure API configuration':'安全配置 API'} className="mx-3 mb-2 rounded-lg border border-cyber-cyan/30 bg-surface-800 p-3 space-y-2" data-credential-card={provider}>
    <div className="flex justify-between gap-2"><strong className="text-sm">{provider==='nexus'?(en?'Connect Nexus when needed':'按需连接 Nexus'):(en?'Optional: enhanced search':'可选：增强跨站搜索')}</strong>
      <button type="button" disabled={busy} onClick={onClose} className="btn-ghost text-xs">{saved?(en?'Close':'关闭'):(en?'Not now':'暂不配置')}</button></div>
    <CredentialHelp provider={provider} language={language} toast={toast}/>
    {saved?<p role="status" className="text-xs text-cyber-green">{en?'Saved securely. This does not verify account access or website login. Review the previous result before manually continuing; nothing was retried automatically.':'已安全保存，尚不代表账号可用或网站已登录。请检查上次操作结果后手动继续；没有自动重试下载或安装。'}</p>:<>
      <p className="text-xs text-surface-400">{en?'Use this private field, not the message box. The key is not sent as a chat message or to the model.':'请填在下面的安全输入框，不要发到聊天里。密钥不会作为聊天消息发送或交给模型。'}</p>
      <input aria-label={`${GUIDES[provider].name} API Key`} type="password" autoComplete="off" spellCheck={false} value={key} disabled={busy||restart} onChange={e=>setKey(e.target.value)} className="input-cyber"/>
      <button type="button" onClick={save} disabled={busy||restart||!key.trim()} className="btn-cyber text-xs">{restart?(en?'Restart to check saved state':'请重启确认保存状态'):busy?(en?'Saving…':'保存中…'):(en?'Save securely':'安全保存')}</button>
    </>}
  </section>
}
