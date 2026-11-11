const fs = require('node:fs'), path = require('node:path')
const root = path.resolve(__dirname, '../../build/v17-download-panel-ui')
if (!process.versions.electron) {
  fs.mkdirSync(root, {recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname, 'fixtures/download-panel-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"test"'}})
  fs.writeFileSync(path.join(root,'index.html'), '<html><meta charset="utf-8"><div id="root"></div><script src="app.js"></script></html>')
  const result = require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(result.stdout || ''); process.stderr.write(result.stderr || '')
  if(result.error) throw result.error
  process.exit(result.status ?? 1)
} else {
  const {app,BrowserWindow,session} = require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async () => {
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win = new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for (const language of ['zh-CN','en']) for (const mode of ['valid','reject','http','timeout','poll-error','poll-timeout','invalid','cancelled','done','new-generation','language-switch','phases','malformed-detail','malformed-phase','malformed-cancel','malformed-number']) {
      await win.loadFile(path.join(root,'index.html'),{query:{language}})
      await win.webContents.executeJavaScript(`(async()=>{
        const mode=${JSON.stringify(mode)}, f=window.fixture, en=${language === 'en'}
        const wait=async(fn)=>{for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,15))}throw Error('Condition failed: '+mode+' '+document.body.textContent)}
        const content=()=>document.body.textContent
        const button=()=>[...document.querySelectorAll('button')].find(b=>/取消|Cancel/.test(b.textContent))
        const check=(ok,message)=>{if(!ok)throw Error(mode+': '+message)}
        await wait(button)
        f.mode=mode
        if(mode==='language-switch'){
          button().click()
          f.setLanguage(en?'zh-CN':'en')
          await wait(()=>content().includes('TASK_CANCEL_REQUESTED'))
          check(content().includes(en?'已请求取消':'Cancellation requested'),'response uses stale language')
          f.setLanguage(en?'en':'zh-CN')
          await wait(()=>content().includes(en?'Cancellation requested':'已请求取消'))
          check(f.cancels===1,'language switch repeated cancellation')
          check(f.events.filter(event=>event==='download-start').length===1,'language switch restarted polling')
        }else if(mode==='phases'){
          for(const phase of ['cache_hit','preparing','browser_opened','browser_preparing','waiting_verification','verification_resolved','browser_downloading','browser_download_complete','transferring','importing','verifying','download_complete']){
            f.state={...f.state,items:f.state.items.map(item=>({...item,phase,phase_label:'中文阶段提示',source:'workshop',source_label:'Steam 创意工坊'})),elapsed_seconds:65,current_item:{phase:'transferring'},eta_seconds:121}
            const before=f.polls
            await wait(()=>f.polls>=before+2)
            check(content().includes(en?'Elapsed 1m 5s':'已用 1 分 5 秒'),'duration not localized')
            check(content().includes(en?'Remaining ~2m 1s':'剩余 约 2 分 1 秒'),'ETA not localized')
            if(en)check(!/[\\u4e00-\\u9fff]/.test(content()),'Chinese phase/source label in English mode: '+phase)
          }
          f.state={...f.state,items:f.state.items.map(item=>({...item,phase:'future_phase',phase_label:'',status:'future_status'}))}
          await wait(()=>content().includes(en?'Status unverified':'状态待核验'))
          for(const unusual of ['constructor','__proto__']) {
            f.state={...f.state,task_kind:unusual,items:f.state.items.map(item=>({...item,phase:unusual}))}
            const before=f.polls
            await wait(()=>f.polls>=before+2)
            check(content().includes(en?'Status unverified':'状态待核验'),'unknown key crashed panel')
            check(content().includes(en?'Processing':'正在处理'),'unknown task type not handled')
          }
        }else if(['poll-error','poll-timeout','invalid'].includes(mode) || mode.startsWith('malformed-')){
          await wait(()=>content().includes('DOWNLOAD_STATUS_UNAVAILABLE'))
          if(en)check(content().includes('This does not mean the task has stopped'),'missing English failure explanation')
          check(button().disabled,'stale cancel remains enabled')
          check(!content().includes('private fixture error'),'raw error leaked')
          check(!content().includes('private malformed'),'malformed detail leaked')
          f.mode='valid'
          await wait(()=>!content().includes('DOWNLOAD_STATUS_UNAVAILABLE'))
          check(!button().disabled,'recovery remained locked')
        }else if(['done','cancelled','new-generation'].includes(mode)){
          f.state={...f.state,active:false,cancel_requested:mode==='cancelled',generation:mode==='new-generation'?2:1,items:f.state.items.map(item=>({...item,status:mode==='cancelled'?'cancelled':'done'}))}
          await wait(()=>!button() || content().includes(en?'Task cancelled':'任务已取消'))
          check(f.events.includes('download-batch-complete')===(mode==='done'),'incorrect completion feedback')
          if(mode==='cancelled')check(!/正在取消|Cancelling/.test(content()),'terminal state stuck cancelling')
        }else{
          button().click();button().click()
          await wait(()=>content().includes(mode==='valid'?'TASK_CANCEL_REQUESTED':'TASK_CANCEL_UNCONFIRMED'))
          check(f.cancels===1,'duplicate cancellation')
          check(f.body.generation===1,'missing generation guard')
          check(f.events.includes('cancel')===(mode==='valid'),'false cancel feedback')
          check(!content().includes('private fixture error'),'raw error leaked')
        }
        check(f.maxConcurrent===1,'overlapping polls')
        if(en)check(!/[\\u4e00-\\u9fff]/.test(content()),'Chinese built-in UI in English mode')
      })()`)
      results.push({language,mode,passed:true})
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    console.log('Download panel: '+results.length+' scenarios passed')
    win.destroy();app.quit()
  }).catch(error=>{console.error(error);app.exit(1)})
}
