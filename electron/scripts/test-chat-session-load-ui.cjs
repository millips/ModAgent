const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-chat-ui')
if(!process.versions.electron){
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'session-load-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const results=[]
    for(const mode of ['http','invalid','body','late']){
      await win.loadFile(path.join(root,'index.html'),{query:{'session-load':'true'}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Session load did not recover')}
          const original=window.setTimeout.bind(window)
          window.setTimeout=(fn,ms,...a)=>original(fn,ms===15000?150:ms,...a)
          window.fixtureLoadMode=${JSON.stringify(mode)}
          const row=id=>document.querySelector('[data-session-id="'+id+'"]')
          await wait(()=>row('saved-a'))
          row('saved-a').click()
          if(window.fixtureLoadMode==='late')await wait(()=>window.resolveOldSession)
          else await wait(()=>window.fixtureErrors.some(t=>t.includes('SESSION_LOAD_FAILED')))
          row('saved-b').click()
          await wait(()=>document.body.textContent.includes('Transcript saved-b'))
          if(window.resolveOldSession){window.resolveOldSession();await new Promise(r=>setTimeout(r,100))}
          if(document.body.textContent.includes('Transcript saved-a')||!document.body.textContent.includes('Transcript saved-b'))throw Error('Old load replaced current transcript')
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'session-load-result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.mode))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
