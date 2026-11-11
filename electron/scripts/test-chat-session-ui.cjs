const fs=require('node:fs'), path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT || path.resolve(__dirname,'../../build/v17-chat-ui')
if(!process.versions.electron) {
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
} else {
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'session-ops-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:1000,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    await win.loadFile(path.join(root,'index.html'),{query:{'session-ops':'true'}})
    await win.webContents.executeJavaScript(`(async()=>{
      const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Session operation failed')}
      const action=name=>document.querySelector('[data-session-action="'+name+'"]')
      await wait(()=>action('delete'))
      window.fixtureMutationFailure=true
      action('delete').click()
      await wait(()=>window.fixtureErrors.some(t=>t.includes('SESSION_DELETE_FAILED')))
      if(!action('delete') || window.fixtureErrors.some(t=>t==='会话已删除'))throw Error('Failed deletion shown as success')
      action('rename').click()
      await wait(()=>document.querySelector('.chat-session-list input'))
      const field=document.querySelector('.chat-session-list input')
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'Retained title')
      field.dispatchEvent(new Event('input',{bubbles:true}))
      await new Promise(r=>setTimeout(r,40))
      field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
      await wait(()=>window.fixtureErrors.some(t=>t.includes('SESSION_RENAME_FAILED')))
      if(document.querySelector('.chat-session-list input')?.value!=='Retained title')throw Error('Rename draft lost')
      window.fixtureMutationFailure=false
      field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
      await wait(()=>!document.querySelector('.chat-session-list input') && document.body.textContent.includes('Retained title'))
      action('delete').click()
      await wait(()=>!action('delete') && window.fixtureErrors.includes('会话已删除'))
    })()`)
    fs.writeFileSync(path.join(root,'session-ops-result.json'),JSON.stringify({passed:true,checks:['delete-failure-preserves-row','rename-failure-preserves-draft','rename-retry','delete-retry']}))
    console.log('SESSION OPERATIONS UI PASSED: failure is not success; drafts preserved; retry works')
    win.destroy();app.exit(0)
  }).catch(e=>{console.error(e);app.exit(1)})
}
