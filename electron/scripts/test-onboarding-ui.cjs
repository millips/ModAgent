const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/onboarding-ui-20261111')
if(!process.versions.electron){
 fs.mkdirSync(root,{recursive:true})
 const assets=path.resolve(__dirname,'../dist/assets')
 fs.copyFileSync(path.join(assets,fs.readdirSync(assets).find(n=>n.endsWith('.css'))),path.join(root,'style.css'))
 for(const [name,entry] of [['guide','credential-guide-ui'],['chat','conversation-ui']]){
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures',entry+'.jsx')],bundle:true,outfile:path.join(root,name+'.js'),platform:'browser',format:'iife',alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},loader:{'.png':'dataurl','.mp3':'dataurl'},define:{'import.meta.env':'{}','process.env.NODE_ENV':'"test"'}})
  fs.writeFileSync(path.join(root,name+'.html'),`<html><meta charset="utf-8"><link rel="stylesheet" href="style.css"><body data-ma-theme="core"><div id="root"></div><script src="${name}.js"></script></body></html>`)
 }
 const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:60000,windowsHide:true})
 process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');if(r.error)throw r.error;process.exit(r.status??1)
}else{
 const {app,BrowserWindow,session}=require('electron')
 app.setPath('userData',path.join(root,'profile'))
 app.whenReady().then(async()=>{
  session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
  const win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
  const results=[]
  for(const language of ['en','zh-CN'])for(const provider of ['nexus','tavily'])for(const mode of ['success','error','timeout','unavailable','link-error','invalid']){
   await win.loadFile(path.join(root,'guide.html'),{query:{language,provider,mode}})
   try{
    if(mode==='success'){
     await win.webContents.executeJavaScript(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`)
     fs.writeFileSync(path.join(root,`guide-${provider}-${language}.png`),(await win.webContents.capturePage()).toPNG())
    }
    await win.webContents.executeJavaScript(`(async()=>{
     const mode=${JSON.stringify(mode)},provider=${JSON.stringify(provider)}
     const wait=async f=>{for(let i=0;i<100;i++){if(f())return;await new Promise(r=>setTimeout(r,20))}throw Error('Guide wait timeout')}
     await wait(()=>document.querySelector('input[type=password]'))
     const timer=setTimeout.bind(window);window.setTimeout=(fn,ms,...a)=>timer(fn,ms===20000?100:ms,...a)
     const field=document.querySelector('input[type=password]')
     const value=mode==='invalid'?'bad key':'fake-guide-secret'
     Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}))
     await new Promise(r=>setTimeout(r,30))
     const save=()=>[...document.querySelectorAll('button')].find(b=>/安全保存|Save securely|Saving|保存中|重启|Restart/.test(b.textContent))
     document.querySelector('[data-credential-help] button').click()
     await wait(()=>window.guideFixture.opened.length===1)
     save().click();save().click()
     const f=window.guideFixture
     if(['success','link-error'].includes(mode)){
      await wait(()=>f.saved===1)
      if(document.querySelector('input[type=password]'))throw Error('Key retained after success')
      if(!document.body.innerText.match(/没有自动重试|nothing was retried/))throw Error('Missing no-replay guidance')
      if(f.calls.length!==1||Object.keys(f.calls[0]).length!==1||f.calls[0][provider==='nexus'?'nexus_api_key':'tavily_api_key']!==value)throw Error('Wrong secure payload')
     }else{
      await wait(()=>f.toasts.some(t=>t.includes('SETUP_')))
      if(f.saved||field.value!==value)throw Error('Failure lost key or reported success')
      if(mode==='timeout'&&!save().disabled)throw Error('Unknown save allows retry')
      if(['invalid','unavailable'].includes(mode)&&f.calls.length)throw Error('Unsafe secure call')
     }
     if(f.requests.some(r=>r.body.includes(value)||r.url.includes('/chat')))throw Error('Key leaked outside secure IPC')
     if(f.toasts.some(t=>t.includes(value)))throw Error('Secret in toast')
     if(localStorage.length||sessionStorage.length)throw Error('Secret persistence outside vault')
     if(mode==='link-error'&&!f.toasts.some(t=>/Could not open|未能打开/.test(t)))throw Error('Link failure hidden')
    })()`)
    results.push({language,provider,mode,passed:true})
   }catch(e){results.push({language,provider,mode,passed:false,error:e.message})}
  }
  for(const provider of ['nexus','tavily']){
   await win.loadFile(path.join(root,'chat.html'),{query:{credential:provider,language:'en'}})
   try{
    await win.webContents.executeJavaScript(`(async()=>{
     const wait=async f=>{for(let i=0;i<150;i++){if(f())return;await new Promise(r=>setTimeout(r,20))}throw Error('Chat integration timeout')}
     await wait(()=>document.querySelector('.chat-composer textarea'))
     const input=document.querySelector('.chat-composer textarea')
     Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'fixture request');input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,50));input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
     await wait(()=>document.querySelector('[data-credential-card="${provider}"]'))
     const before=window.fixtureRequests.filter(r=>r.url.endsWith('/chat/stream')).length
     window.modagent={saveSecrets:async()=>({ok:true})}
     const secret=document.querySelector('input[type=password]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(secret,'private-fixture-key');secret.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,40));[...document.querySelectorAll('button')].find(b=>b.textContent==='Save securely').click()
     await wait(()=>document.body.innerText.includes('Saved securely.'))
     if(window.fixtureRequests.some(r=>JSON.stringify(r).includes('private-fixture-key')))throw Error('Chat/config leaked secret')
     if(window.fixtureRequests.filter(r=>r.url.endsWith('/chat/stream')).length!==before)throw Error('Credential save replayed chat')
    })()`)
    results.push({provider,mode:'actual-chat',passed:true})
   }catch(e){results.push({provider,mode:'actual-chat',passed:false,error:e.message,diagnostic:await win.webContents.executeJavaScript('({body:document.body.innerText.slice(-1800),requests:window.fixtureRequests})')})}
  }
  fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2));results.forEach(r=>console.log(JSON.stringify(r)));win.destroy();app.exit(results.every(r=>r.passed)?0:1)
 }).catch(e=>{console.error(e);app.exit(1)})
}
