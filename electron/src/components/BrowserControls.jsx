import React, {useEffect, useState} from 'react'

export default function BrowserControls({language='zh-CN',compact=false}) {
  const en=language==='en', ui=(zh,english)=>en?english:zh
  const [state,setState]=useState(null), [busy,setBusy]=useState(false), [error,setError]=useState('')
  const bridge=window.modagent
  useEffect(()=>{
    if(!bridge?.getBrowserStatus)return
    let cancelled=false,timer
    const refresh=async()=>{
      try {const next=await bridge.getBrowserStatus();if(!cancelled)setState(next)}catch{}
      if(!cancelled)timer=setTimeout(refresh,2000)
    }
    refresh()
    return()=>{cancelled=true;clearTimeout(timer)}
  },[])
  if(!state || state.phase==='disabled')return null
  const ready=state.phase==='ready', starting=state.phase==='starting'
  const action=async(method,argument)=>{
    if(busy)return
    setBusy(true);setError('')
    try {
      const result=await bridge[method](argument)
      if(!result?.ok && !result?.cancelled)setError(ui('操作未完成。请检查浏览器状态；手动选择仅支持 Chrome、Edge、Brave。','Could not complete the action. Check browser status; only Chrome, Edge and Brave can be selected.'))
      setState(await bridge.getBrowserStatus())
    } catch {setError(ui('浏览器暂时无法操作，请稍后重试。','Browser control is unavailable. Try again.'))}
    finally{setBusy(false)}
  }
  return <section data-browser-controls className={compact?'mx-3 my-1 text-xs space-y-1':'card-cyber text-xs space-y-2'}>
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-surface-500">{ready?`${ui('浏览器','Browser')} · ${state.name}`:starting?ui('正在连接浏览器…','Connecting browser…'):ui('浏览器需要处理','Browser needs attention')}</span>
      {ready?<>
        <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('showBrowser')}>{ui('显示浏览器','Show browser')}</button>
        <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('minimizeBrowser')}>{ui('登录完成，收起','Done, minimize')}</button>
        {!compact && <>
          <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('showBrowser',{site:'nexus'})}>{ui('登录 Nexus','Sign in to Nexus')}</button>
          <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('showBrowser',{site:'steam'})}>{ui('登录 Steam 社区','Sign in to Steam Community')}</button>
        </>}
      </>:!starting && <>
        <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('retryBrowser')}>{ui('重新检测','Retry')}</button>
        <button type="button" disabled={busy} className="btn-ghost text-xs" onClick={()=>action('selectBrowser')}>{ui('选择已安装浏览器','Locate installed browser')}</button>
      </>}
    </div>
    {!ready && !starting && <>
      <p className="text-cyber-yellow">{state.error==='browser_port_busy'
        ?ui('浏览器连接被占用。请关闭旧 ModAgent 的专用浏览器后重试。','Browser connection is occupied. Close the old ModAgent browser and retry.')
        :state.phase==='closed'?ui('专用浏览器已关闭，需要网页操作时可重新打开；登录资料保留。','The dedicated browser is closed. Reopen it when needed; its profile is retained.')
        :ui('未找到可用的 Chrome、Edge 或 Brave。安装其中一个或选择安装位置，再重新检测。IE 不受支持。','No usable Chrome, Edge or Brave found. Install one or locate it, then retry. Internet Explorer is not supported.')}</p>
      <div className="flex flex-wrap gap-3">{['edge','chrome','brave'].map(id=><button key={id} type="button" disabled={busy} className="text-cyber-cyan" onClick={()=>action('openBrowserDownload',id)}>{ui('官网下载','Official download')} {id==='edge'?'Edge':id==='chrome'?'Chrome':'Brave'} ↗</button>)}</div>
    </>}
    {ready && (state.fallback || state.changedBrowser) && <p className="text-cyber-yellow">{ui('已改用可用浏览器。原浏览器资料未删除；不同浏览器需要各自登录。','Using a working fallback. The original profile is retained; browsers have separate sign-ins.')}</p>}
    {ready && state.preferenceNotSaved && <p className="text-cyber-yellow">{ui('未能记住浏览器选择，下次启动可能重新检测。','Could not remember this choice; the next launch may detect browsers again.')}</p>}
    {!compact && <p className="text-surface-500">{ui('默认最小化运行。需要登录或验证时恢复窗口；登录后点击“收起”继续后台工作。此处使用 ModAgent 专用登录资料。','Starts minimized. Login or verification restores the window; minimize it afterward to continue in the background. This uses the dedicated ModAgent browser profile.')}</p>}
    {error && <p role="alert" className="text-cyber-yellow">{error}</p>}
  </section>
}
