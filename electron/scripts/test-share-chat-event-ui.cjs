// Run after test-conversation-ui.cjs rebuilds the shared real ChatPage fixture.
const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-chat-ui')
if(!process.versions.electron){
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'share-event-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for(const language of ['en','zh-CN'])for(const official of [true,false])for(const prerequisite of [true,false]){
      const mode={language,official,prerequisite}
      await win.loadFile(path.join(root,'index.html'),{query:{language}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20))}throw Error('Share event did not reach draft')}
          await wait(()=>document.querySelector('textarea'))
          await new Promise(r=>setTimeout(r,80))
          const request=mode.official?{type:'official',shareId:'ma-fixture'}:{type:'private',share:'fixture-share'}
          request.action=mode.prerequisite?'prerequisite_plan':'install_plan'
          window.dispatchEvent(new CustomEvent('modagent:share-plan',{detail:request}))
          const marker=mode.official?'ma-fixture':'fixture-share'
          const boundary=mode.language==='en'?(mode.prerequisite?'Do not install the main Mods':'Do not install directly'):(mode.prerequisite?'不得安装主体 Mod':'不要直接安装')
          await wait(()=>document.querySelector('textarea').value.includes(marker)&&document.querySelector('textarea').value.includes(boundary))
          const draft=document.querySelector('textarea').value
          if(!draft.includes(boundary))throw Error('Lost plan/authorization boundary')
          if(mode.language==='en'&&/[\\u4e00-\\u9fff]/.test(draft))throw Error('English draft contains Chinese')
          if(sessionStorage.getItem('chat_draft')!==draft)throw Error('Draft not retained')
          window.dispatchEvent(new CustomEvent('modagent:share-plan',{detail:{}}))
          await new Promise(r=>setTimeout(r,40))
          if(document.querySelector('textarea').value!==draft)throw Error('Empty event erased draft')
          if(window.fixtureRequests.some(r=>r.url.endsWith('/chat/stream')||r.url.includes('/tool/')))throw Error('Share event performed work without send')
        })()`)
        results.push({...mode,passed:true})
      }catch(e){results.push({...mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'share-event-result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+JSON.stringify(r)))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
