const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-chat-ui')
if(!process.versions.electron){
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'scope-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const results=[]
    for(const mode of ['preparation-game','stream-game','stream-session','recovery-http','recovery-body','recovery-invalid','recovery-complete','recovery-cancel','recovery-switch']){
      await win.loadFile(path.join(root,'index.html'),{query:{'session-load':'true',recovery:mode.startsWith('recovery-')?mode.slice(9):''}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Scope condition failed '+mode)}
          const send=async text=>{
            const field=document.querySelector('textarea')
            Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(field,text)
            field.dispatchEvent(new Event('input',{bubbles:true}))
            await new Promise(r=>setTimeout(r,40))
            field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
          }
          await wait(()=>document.querySelector('textarea'))
          if(mode.startsWith('recovery-')){
            if(mode==='recovery-complete'){
              await wait(()=>window.fixtureRequests.some(r=>r.url.includes('/chat/tasks/saved-a?'))&&!document.querySelector('button[title="停止"]'))
              if(window.fixtureErrors.some(t=>/TASK_RECOVERY_FAILED|TASK_VIEW_DETACHED/.test(t)))throw Error('Completed recovery presented as failed/detached')
            }else if(['recovery-http','recovery-body','recovery-invalid'].includes(mode)){
              await wait(()=>window.fixtureErrors.some(t=>t.includes('TASK_RECOVERY_FAILED')))
              await wait(()=>!document.querySelector('button[title="停止"]'))
            }else{
              await wait(()=>document.querySelector('button[title="停止"]'))
              if(mode==='recovery-cancel'){
                document.querySelector('button[title="停止"]').click()
                await wait(()=>window.fixtureRequests.some(r=>r.url.endsWith('/tasks/cancel')&&r.body.session_id==='saved-a'))
              }else{
                document.querySelector('[data-session-id="saved-b"]').click()
                await wait(()=>document.body.textContent.includes('Transcript saved-b'))
              }
              await wait(()=>!document.querySelector('button[title="停止"]'))
              await new Promise(r=>setTimeout(r,300))
              if(window.fixtureErrors.some(t=>t.includes('TASK_RECOVERY_FAILED')))throw Error('Superseded recovery polluted current view')
            }
            return
          }
          window.fixtureDelaySession=mode==='preparation-game'
          window.fixtureTransportFailure=mode==='preparation-game'?'':'body'
          await send('Old game request')
          if(mode==='preparation-game')await wait(()=>window.resolveDelayedSession)
          else await wait(()=>document.querySelector('button[title="停止"]'))
          if(mode==='stream-session')document.querySelector('[data-session-id="saved-b"]').click()
          else window.fixtureSwitchGame()
          await wait(()=>!document.querySelector('button[title="停止"]')&&!document.querySelector('textarea').readOnly)
          if(mode==='preparation-game'){
            window.resolveDelayedSession();await new Promise(r=>setTimeout(r,80))
            if(window.fixtureRequests.some(r=>r.url.endsWith('/chat/stream')))throw Error('Old preparation started a chat in new game')
            if(document.querySelector('textarea').value!=='Old game request')throw Error('Draft lost across game switch')
          }
          window.fixtureDelaySession=false;window.fixtureTransportFailure=''
          await send('mod是什么')
          await wait(()=>document.body.textContent.includes('是游戏的修改或扩展'))
          if(window.fixtureRequests.some(r=>r.url.endsWith('/tasks/cancel')))throw Error('View change cancelled a background task')
          if(mode==='preparation-game'){
            const creates=window.fixtureRequests.filter(r=>r.url.endsWith('/sessions')&&r.method==='POST')
            if(creates[0].body.game_slug!=='fixturegame'||creates.at(-1).body.game_slug!=='otherfixture')throw Error('Session game scope lost')
          }
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message,diagnostic:await win.webContents.executeJavaScript('({requests:window.fixtureRequests,errors:window.fixtureErrors,body:document.body.textContent.slice(-800)})')})}
    }
    fs.writeFileSync(path.join(root,'scope-result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.mode))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
