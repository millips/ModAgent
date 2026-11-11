// Exercise the actual production bootstrap when its main chunk cannot load.
const fs=require('node:fs'),path=require('node:path')
const root=path.resolve(__dirname,'../../build/v17-startup-failure')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  const result=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:20000,windowsHide:true})
  process.stdout.write(result.stdout||'');process.stderr.write(result.stderr||'')
  if(result.error)throw result.error
  process.exit(result.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    let blocked=0
    session.defaultSession.webRequest.onBeforeRequest({urls:['file:///*','http://*/*','https://*/*']},(details,cb)=>{
      const chunk=/\/main-[^/]+\.js(?:\?|$)/.test(details.url)
      if(chunk)blocked++
      cb({cancel:chunk||/^https?:/.test(details.url)})
    })
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    await win.loadFile(path.resolve(__dirname,'../dist/index.html'))
    await win.webContents.executeJavaScript(`(async()=>{
      for(let i=0;i<100;i++){
        const text=document.body.textContent
        if(text.includes('UI_STARTUP_FAILED')){
          if(!document.querySelector('[role="alert"] button'))throw Error('No recovery control')
          if(!text.includes('后台任务可能仍在运行')||!text.includes('Background tasks may still be running'))throw Error('Missing bilingual task warning')
          return
        }
        await new Promise(resolve=>setTimeout(resolve,20))
      }
      throw Error('Production bootstrap did not show failure UI')
    })()`)
    if(!blocked)throw Error('Main chunk was not blocked; test did not exercise loading failure')
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,blockedMainRequests:blocked}))
    console.log('Production startup failure passed: blocked main chunk, bilingual recovery UI and reload control visible')
    win.destroy();app.quit()
  }).catch(error=>{console.error(error);app.exit(1)})
}
