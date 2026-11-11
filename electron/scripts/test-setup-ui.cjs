const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-setup-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/setup-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"test"'}})
  const assets=path.resolve(__dirname,'../dist/assets')
  const css=fs.readdirSync(assets).find(name=>name.endsWith('.css'))
  fs.copyFileSync(path.join(assets,css),path.join(root,'style.css'))
  fs.writeFileSync(path.join(root,'index.html'),'<html><meta charset="utf-8"><link rel="stylesheet" href="style.css"><body data-ma-theme="core"><div id="root"></div><script src="app.js"></script></body></html>')
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:45000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const results=[]
    for(const language of ['zh-CN','en'])for(const mode of ['success','credential-error','credential-timeout','config-http','config-body','config-invalid']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode,language}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const en=${language==='en'}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Setup did not recover '+mode)}
          const timer=window.setTimeout.bind(window)
          window.setTimeout=(fn,ms,...a)=>timer(fn,[15000,20000].includes(ms)?150:ms,...a)
          const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes(en?({'保存并进入':'Save and enter','请重启确认保存状态':'Restart to verify save'}[text]||text):text))
          await wait(()=>document.querySelectorAll('input[type=password]').length===1)
          if(mode==='success'){
            const provider=document.querySelectorAll('select')[1]
            const set=v=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(provider,v);provider.dispatchEvent(new Event('change',{bubbles:true}))}
            set('custom');await new Promise(r=>setTimeout(r,30))
            if(!button('保存并进入').disabled||!document.querySelector('details').open)throw Error('Custom endpoint/model fields must be visible and required')
            set('deepseek');await new Promise(r=>setTimeout(r,30))
          }
          const field=[...document.querySelectorAll('input[type=password]')].at(-1)
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'fake-test-key')
          field.dispatchEvent(new Event('input',{bubbles:true}))
          await new Promise(r=>setTimeout(r,40))
          await wait(()=>button('保存并进入'))
          const save=button('保存并进入')
          save.click(); save.click()
          if(mode==='success')await wait(()=>window.setupFixture.done===1)
          else {
            const code=mode==='credential-timeout'?'SETUP_SAVE_UNCONFIRMED':mode==='credential-error'?'SETUP_CREDENTIAL_FAILED':'SETUP_CONFIG_FAILED'
            await wait(()=>window.setupFixture.toasts.some(t=>t.includes(code)))
            if(window.setupFixture.done)throw Error('Failed save entered workspace')
            if(mode.startsWith('config-')&&!window.setupFixture.toasts.some(t=>t.includes(en?'Credentials were saved securely':'密钥已安全保存')))throw Error('Partial save incorrectly reported')
            if(mode==='credential-timeout'&&!button('请重启确认保存状态')?.disabled)throw Error('Unconfirmed secure save allows duplicate retry')
            await wait(()=>document.querySelectorAll('input[type=password]').length===1)
            if([...document.querySelectorAll('input[type=password]')].at(-1).value!=='fake-test-key')throw Error('Input lost after failure')
          }
          if(window.setupFixture.stores!==1)throw Error('Duplicate secure writes')
          if(window.setupFixture.requests.some(r=>r.url.endsWith('/chat/reset')))throw Error('Redundant reset')
          if(window.setupFixture.requests.some(r=>r.body?.includes('fake-test-key')))throw Error('Secure key resent through config')
        })()`)
        results.push({mode,language,passed:true})
        if(mode==='success')fs.writeFileSync(path.join(root,`setup-${language}.png`),(await win.webContents.capturePage()).toPNG())
      }catch(e){results.push({mode,language,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.language+' '+r.mode))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
