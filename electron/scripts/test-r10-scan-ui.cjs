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
      return {passed:true,...window.fixture}
    })()`)
    if(errors.length) throw Error(errors.join('\n'))
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(result,null,2))
    console.log('Actual ChatPage scan button: zero imports refreshed 0 to 97; passed')
    win.destroy(); app.exit(0)
  }).catch(e=>{console.error(e);app.exit(1)})
}
