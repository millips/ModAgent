const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-error-boundary-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/error-boundary-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"production"'}})
  fs.writeFileSync(path.join(root,'index.html'),'<html><meta charset="utf-8"><div id="root"></div><script src="app.js"></script></html>')
  const result=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(result.stdout||'');process.stderr.write(result.stderr||'')
  if(result.error)throw result.error
  process.exit(result.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for(const language of ['en','zh-CN'])for(const mode of ['success','error','timeout','missing','initial']){
      await win.loadFile(path.join(root,'index.html'),{query:{language,mode}})
      await win.webContents.executeJavaScript(`(async()=>{
        const en=${language==='en'},mode=${JSON.stringify(mode)},f=window.fixture
        const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20))}throw Error('Recovery condition failed '+mode)}
        const check=(ok,message)=>{if(!ok)throw Error(mode+': '+message)}
        const text=()=>document.body.textContent
        const button=label=>[...document.querySelectorAll('button')].find(b=>b.textContent===label)
        if(mode!=='initial'){
          await wait(()=>button('Trigger fixture failure'))
          check(!text().includes('UI_RENDER_FAILED'),'healthy child replaced')
          button('Trigger fixture failure').click()
        }
        await wait(()=>text().includes('UI_RENDER_FAILED'))
        check(text().includes(en?'Background tasks may still be running':'后台任务可能仍在运行'),'missing ongoing-task warning')
        check(text().includes(en?'Unsaved input may be lost':'未保存的输入可能已丢失'),'draft loss hidden')
        check(!text().includes('private render'),'raw render error leaked into UI')
        check(f.reloads===0&&f.requests===0,'recovery automatically retried work')
        const open=button(en?'Open logs folder':'打开日志目录');open.click();open.click()
        const expected=mode==='error'?'MAINTENANCE_FAILED':mode==='timeout'?'MAINTENANCE_TIMEOUT':mode==='missing'?'MAINTENANCE_UNAVAILABLE':en?'system confirmed':'系统已确认'
        await wait(()=>text().includes(expected))
        check(f.opens===(mode==='missing'?0:1),'duplicate native open')
        check(!text().includes('private native'),'raw native error leaked into UI')
        check(localStorage.getItem('fixture-saved-settings')==='saved-only-fixture','saved settings changed')
        if(en)check(!/[\\u4e00-\\u9fff]/.test(text()),'Chinese fallback in English')
        button(en?'Reload interface':'重新加载界面').click()
        check(f.reloads===1&&f.requests===0,'explicit reload replayed operation')
      })()`)
      results.push({language,mode,passed:true})
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    console.log('Error boundary: '+results.length+' production React scenarios passed')
    win.destroy();app.quit()
  }).catch(error=>{console.error(error);app.exit(1)})
}
