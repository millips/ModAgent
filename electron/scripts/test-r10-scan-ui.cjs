const fs = require('node:fs'), path = require('node:path')
const root = path.resolve(__dirname, '../../build/reliability-r10/scan-ui')
if (!process.versions.electron) {
  fs.mkdirSync(root, { recursive: true })
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/r10-scan-ui.jsx')], bundle:true,
    outfile:path.join(root,'app.js'), platform:'browser', format:'iife', loader:{'.png':'dataurl'},
    alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},
    define:{__MODAGENT_SUBSCRIPTION__:'false',__MODAGENT_VERSION__:'"r10-test"','import.meta.env':'{}','process.env.NODE_ENV':'"test"'}})
  fs.writeFileSync(path.join(root,'index.html'), '<meta charset="utf-8"><div id="root"></div><script src="app.js"></script>')
  const r = require('node:child_process').spawnSync(require('electron'), [__filename], {encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||''); process.stderr.write(r.stderr||'')
  if(r.error) throw r.error
  process.exit(r.status??1)
} else {
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'isolated-profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const errors=[]
    win.webContents.on('console-message',(_e,level,msg)=>{if(level>=3)errors.push(msg)})
    await win.loadFile(path.join(root,'index.html'))
    const result=await win.webContents.executeJavaScript(`(async()=>{
      const wait=async(p)=>{for(let i=0;i<80;i++){if(p())return;await new Promise(r=>setTimeout(r,50))}throw Error('UI timeout')}
      const button=()=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='扫描已有 Mod')
      await wait(button); button().click()
      await wait(()=>document.querySelector('#inventory-count').textContent==='97')
      if(window.fixture.refreshes!==1)throw Error('Refresh count incorrect')
      if(!window.fixture.toasts.some(t=>t.includes('没有新增管理记录')))throw Error('Missing truthful scan result')
      await wait(()=>button()&&!button().disabled)
      const timer=window.setTimeout.bind(window)
      window.setTimeout=(fn,ms,...args)=>timer(fn,ms===120000?100:ms,...args)
      window.fixture.hang=true
      const scanButton=button()
      scanButton.click();scanButton.click()
      await wait(()=>window.fixture.toasts.some(t=>t.includes('SCAN_UNCONFIRMED')))
      await wait(()=>button()&&!button().disabled)
      if(window.fixture.calls.filter(url=>url.endsWith('/tool/scan_existing_mods')).length!==2)throw Error('Duplicate scan requests')
      if(window.fixture.refreshes!==2)throw Error('Failure skipped inventory refresh')
      window.fixture.hang=false
      window.fixture.scanResult={status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE',error:'PRIVATE_FIXTURE'}
      const priorToasts=window.fixture.toasts.length
      button().click()
      await wait(()=>window.fixture.toasts.slice(priorToasts).some(t=>t.includes('SCAN_DIRECTORY_UNREADABLE')))
      await wait(()=>button()&&!button().disabled)
      const readErrorToasts=window.fixture.toasts.slice(priorToasts)
      if(!readErrorToasts.some(t=>t.includes('文件夹权限')))throw Error('Missing actionable read error')
      if(readErrorToasts.some(t=>t.includes('PRIVATE_FIXTURE')||t.includes('扫描完成：')))throw Error('Unsafe or false success message')
      if(window.fixture.refreshes!==3)throw Error('Read failure skipped refresh')
      window.fixture.scanResult={identified:[{name:'Fixture'}],detected:1}
      const malformedStart=window.fixture.toasts.length
      button().click()
      await wait(()=>window.fixture.toasts.slice(malformedStart).some(t=>t.includes('SCAN_UNCONFIRMED')))
      await wait(()=>button()&&!button().disabled)
      if(window.fixture.toasts.slice(malformedStart).some(t=>t.includes('扫描完成：')))throw Error('Missing import count reported success')
      if(window.fixture.refreshes!==4)throw Error('Malformed receipt skipped refresh')
      window.fixture.scanResult={identified:[],imported:0,missing_roots:['PRIVATE_FIXTURE']}
      const partialStart=window.fixture.toasts.length
      button().click()
      await wait(()=>window.fixture.toasts.slice(partialStart).some(t=>t.includes('SCAN_PARTIAL')))
      await wait(()=>button()&&!button().disabled)
      const partialToasts=window.fixture.toasts.slice(partialStart)
      if(!partialToasts.some(t=>t.includes('更新已保存的目录')))throw Error('Missing partial scan next step')
      if(partialToasts.some(t=>t.includes('扫描完成：')||t.includes('PRIVATE_FIXTURE')))throw Error('False success or exposed private path')
      if(window.fixture.refreshes!==5)throw Error('Partial scan skipped refresh')
      const directoryButton=()=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes('添加 Mod 目录'))
      for(const [backgroundResult,expected] of [
        [{status:'completed',detected:1,imported:1,missing_roots:['PRIVATE_FIXTURE']},'SCAN_PARTIAL'],
        [{status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE',error:'PRIVATE_FIXTURE'},'SCAN_DIRECTORY_UNREADABLE'],
        [{status:'completed',detected:1,imported:0,missing_roots:[]},'扫描完成：']]){
        window.fixture.backgroundResult=backgroundResult
        const begin=window.fixture.toasts.length
        await wait(()=>directoryButton()&&!directoryButton().disabled)
        directoryButton().click()
        await wait(()=>window.fixture.toasts.slice(begin).some(t=>t.includes(expected)))
        if(window.fixture.toasts.slice(begin).some(t=>t.includes('PRIVATE_FIXTURE')))throw Error('Background private error exposed')
        if(expected!=='扫描完成：'&&window.fixture.toasts.slice(begin).some(t=>t.includes('扫描完成：')))throw Error('Background false success')
      }
      window.fixture.setLanguage('en')
      const englishDirectory=()=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Add Mod directory'))
      await wait(englishDirectory)
      if(!englishDirectory().title.includes('Future scans'))throw Error('English directory tooltip missing')
      for(const [saveResult,expected] of [
        [{status:'running',queued:true},'SCAN_DIRECTORY_UNREADABLE'],
        [{status:'completed',queued:false,imported:0,detected:0,missing_roots:['PRIVATE_FIXTURE']},'SCAN_PARTIAL'],
        [{status:'completed',queued:false,imported:0,detected:0},'Scan completed:'],
        [{status:'completed',queued:false,imported:2,detected:0},'MOD_DIRECTORY_UNCONFIRMED']]){
        window.fixture.saveResult=saveResult
        window.fixture.backgroundResult={status:'failed',error_code:'SCAN_DIRECTORY_UNREADABLE'}
        const begin=window.fixture.toasts.length
        await wait(()=>englishDirectory()&&!englishDirectory().disabled)
        englishDirectory().click()
        await wait(()=>window.fixture.toasts.slice(begin).some(t=>t.includes(expected)))
        const messages=window.fixture.toasts.slice(begin)
        if(messages.some(t=>/[\\u4e00-\\u9fff]/.test(t)||t.includes('PRIVATE_FIXTURE')))throw Error('English directory flow leaked Chinese/private text')
        if(expected!=='Scan completed:'&&messages.some(t=>t.includes('Scan completed:')))throw Error('Immediate directory result false success')
      }
      const namedButton=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
      namedButton('Import game').click()
      await wait(()=>document.querySelector('[role="dialog"]'))
      const dialog=()=>document.querySelector('[role="dialog"]')
      if(/[\\u4e00-\\u9fff]/.test(dialog().textContent))throw Error('Untranslated English import dialog')
      for(const mode of ['cancel','reject','hang']){
        window.fixture.pickerMode=mode
        const begin=window.fixture.toasts.length
        const calls=window.fixture.pickerCalls||0
        window.setTimeout=(fn,ms,...args)=>timer(fn,ms===60000?100:ms,...args)
        const pick=namedButton('Choose folder');pick.click();pick.click()
        await new Promise(r=>timer(r,30))
        await wait(()=>!namedButton('Choose folder').disabled)
        if(window.fixture.pickerCalls!==calls+1)throw Error('Picker call count incorrect: '+mode+' '+calls+' -> '+window.fixture.pickerCalls)
        const messages=window.fixture.toasts.slice(begin)
        if(mode==='cancel'&&messages.length)throw Error('Cancellation treated as error')
        if(mode!=='cancel'&&!messages.some(t=>t.includes('GAME_PICKER_FAILED')))throw Error('Picker failure missing guidance')
        if(messages.some(t=>t.includes('PRIVATE_FIXTURE')))throw Error('Picker exception leaked')
      }
      window.fixture.pickerMode='normal'
      namedButton('Choose folder').click()
      await wait(()=>!namedButton('Import and switch').disabled)
      window.releasePicker({path:'X:/Stale',suggestedName:'Stale'})
      await new Promise(r=>timer(r,30))
      if([...dialog().querySelectorAll('input')].some(i=>i.value.includes('Stale')))throw Error('Late picker overwrote form')
      namedButton('Cancel').click()
      await wait(()=>!dialog())
      for(const [scan,expected] of [
        [undefined,'SCAN_STATUS_UNCONFIRMED'],
        [{game_instance_id:'other',status:'completed',detected:0,imported:0},'SCAN_STATUS_UNCONFIRMED'],
        [{game_instance_id:'fixture',status:'completed',detected:3,imported:0},'Scan completed:'],
        [{game_instance_id:'fixture',status:'failed',error:'PRIVATE_FIXTURE'},'SCAN_FAILED'],
        [{game_instance_id:'fixture',status:'completed',detected:0,imported:0,missing_roots:['PRIVATE_FIXTURE']},'SCAN_PARTIAL']]){
        window.fixture.importScan=scan
        namedButton('Import game').click()
        await wait(()=>namedButton('Choose folder'))
        namedButton('Choose folder').click()
        await new Promise(r=>timer(r,30))
        await wait(()=>namedButton('Import and switch')&&!namedButton('Import and switch').disabled)
        const begin=window.fixture.toasts.length
        const before=window.fixture.importCalls||0
        const submit=namedButton('Import and switch');submit.click();submit.click()
        await wait(()=>window.fixture.toasts.slice(begin).some(t=>t.includes(expected)))
        await wait(()=>!namedButton('Import and switch'))
        if(window.fixture.importCalls!==before+1)throw Error('Duplicate game import')
        const messages=window.fixture.toasts.slice(begin)
        if(messages.some(t=>t.includes('PRIVATE_FIXTURE')||/[\\u4e00-\\u9fff]/.test(t)))throw Error('Unsafe or untranslated import feedback')
        if(expected!=='Scan completed:'&&messages.some(t=>t.includes('Scan completed:')))throw Error('False import scan success')
      }
      namedButton('Import game').click()
      await wait(()=>namedButton('Choose folder'));namedButton('Choose folder').click()
      await new Promise(r=>timer(r,30))
      await wait(()=>namedButton('Import and switch')&&!namedButton('Import and switch').disabled)
      window.fixture.importRejected=true
      const rejectionStart=window.fixture.toasts.length
      namedButton('Import and switch').click()
      await wait(()=>window.fixture.toasts.slice(rejectionStart).some(t=>t.includes('GAME_IMPORT_REJECTED')))
      await wait(()=>namedButton('Import and switch')&&!namedButton('Import and switch').disabled)
      const values=[...document.querySelectorAll('input')].map(i=>i.value)
      if(!values.includes('Fixture Game')||!values.includes('X:/FixtureGame'))throw Error('Rejected import lost form')
      window.fixture.importRejected=false
      window.fixture.holdImport=true
      namedButton('Import and switch').click()
      await wait(()=>namedButton('Importing…'))
      if([...dialog().querySelectorAll('input,button')].some(el=>!el.disabled))throw Error('Import form editable during submission')
      window.releaseImport()
      await wait(()=>!namedButton('Import and switch'))
      await wait(()=>!dialog())
      window.fixture.setLanguage('zh-CN')
      await wait(()=>namedButton('手动导入游戏'))
      namedButton('手动导入游戏').click()
      await wait(dialog)
      if(!dialog().textContent.includes('Nexus 游戏标识（可选）')||!namedButton('导入并切换'))throw Error('Chinese import labels missing')
      namedButton('取消').click()
      await wait(()=>!dialog())
      const {setLanguage,...serializableFixture}=window.fixture
      return {passed:true,...serializableFixture}
    })()`)
    if(errors.length) throw Error(errors.join('\n'))
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(result,null,2))
    console.log('Actual ChatPage scan button: zero imports, timeout, duplicate guard, read-error guidance and retry readiness passed')
    win.destroy(); app.exit(0)
  }).catch(e=>{console.error(e);app.exit(1)})
}
