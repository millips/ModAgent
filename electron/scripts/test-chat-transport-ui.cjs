// Uses the conversation fixture built by test-conversation-ui.cjs.
const fs = require('node:fs')
const path = require('node:path')
const root = process.env.MODAGENT_UI_TEST_OUTPUT || path.resolve(__dirname, '../../build/v17-chat-ui')
if (!process.versions.electron) {
  const result = require('node:child_process').spawnSync(require('electron'), [__filename], {encoding:'utf8', timeout:30000, windowsHide:true})
  process.stdout.write(result.stdout || ''); process.stderr.write(result.stderr || '')
  if(result.error) throw result.error
  process.exit(result.status ?? 1)
} else {
  const {app, BrowserWindow, session} = require('electron')
  app.setPath('userData', path.join(root, 'transport-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']}, (_d, cb)=>cb({cancel:true}))
    const win = new BrowserWindow({show:false, webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const results=[]
    for(const scenario of ['headers','body','partial','http-body','session-http','session-body','session-id','cancel-http','cancel-body','cancel-missing','cancel-requested','cancel-invalidated']) {
      await win.loadFile(path.join(root,'index.html'))
      try {
        await win.webContents.executeJavaScript(`(async()=>{
          const wait=async(fn)=>{for(let i=0;i<80;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Transport did not recover')}
          const nativeTimeout=window.setTimeout.bind(window)
          // Accelerate only the transport's production 45-second deadline.
          const scenario=${JSON.stringify(scenario)}
          const cancelTest=scenario.startsWith('cancel-')
          window.setTimeout=(fn,ms,...args)=>nativeTimeout(fn,(ms===15000 || (ms===45000 && !cancelTest))?150:ms,...args)
          const sessionTest=scenario.startsWith('session-')
          window.fixtureTransportFailure=sessionTest?'':cancelTest?'body':scenario
          window.fixtureSessionFailure=sessionTest?scenario.slice(8):''
          window.fixtureCancelMode=cancelTest?scenario.slice(7):''
          await wait(()=>document.querySelector('textarea'))
          const send=async text=>{
            const field=document.querySelector('textarea')
            Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(field,text)
            field.dispatchEvent(new Event('input',{bubbles:true}))
            await new Promise(r=>setTimeout(r,40))
            field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}))
          }
          await send('transport fixture')
          if(cancelTest) {
            await wait(()=>document.querySelector('button[title="停止"]'))
            document.querySelector('button[title="停止"]').click()
            const expected={http:'TASK_CANCEL_FAILED',body:'TASK_CANCEL_FAILED',missing:'TASK_CANCEL_UNCONFIRMED',requested:'TASK_CANCEL_REQUESTED',invalidated:'TASK_TURN_INVALIDATED'}[window.fixtureCancelMode]
            await wait(()=>window.fixtureErrors.some(t=>t.includes(expected)))
            if(document.body.textContent.includes('CHAT_CONNECTION_TIMEOUT'))throw Error('Manual cancellation mislabeled as timeout')
            window.fixtureTransportFailure=''
            await send('mod是什么')
            await wait(()=>document.body.textContent.includes('是游戏的修改或扩展'))
            return
          }
          if(sessionTest) {
            if(scenario==='session-body') {
              document.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
              document.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
            }
            await wait(()=>window.fixtureErrors.some(text=>text.includes('SESSION_PREPARE_FAILED')))
            if(scenario==='session-body' && window.fixtureRequests.filter(r=>r.url.endsWith('/sessions') && r.method==='POST').length!==1)throw Error('Duplicate preparation requests')
            if(document.querySelector('textarea').value!=='transport fixture')throw Error('Draft lost after preparation failure')
            if(window.fixtureRequests.some(r=>r.url.endsWith('/chat/stream')))throw Error('Chat started without a valid session')
            window.fixtureSessionFailure=''
            await send('mod是什么')
            await wait(()=>document.body.textContent.includes('是游戏的修改或扩展'))
            return
          }
          await wait(()=>document.body.textContent.includes('CHAT_CONNECTION_TIMEOUT'))
          if(!document.body.textContent.includes('后台任务可能仍在运行'))throw Error('Missing background uncertainty')
          if(document.body.textContent.includes('确认下载并安装'))throw Error('Failure exposed install confirmation')
          window.fixtureTransportFailure=''
          await send('mod是什么')
          await wait(()=>document.body.textContent.includes('是游戏的修改或扩展'))
        })()`)
        results.push({scenario,passed:true})
      } catch(e) { results.push({scenario,passed:false,error:e.message}) }
    }
    fs.writeFileSync(path.join(root,'transport-result.json'),JSON.stringify(results,null,2))
    for(const r of results) console.log((r.passed?'PASS ':'FAIL ')+r.scenario)
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
