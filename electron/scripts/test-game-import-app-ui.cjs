const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-game-import-app-ui')
if(!process.versions.electron){
  ;(async()=>{
    fs.mkdirSync(root,{recursive:true})
    await require('esbuild').build({entryPoints:[path.join(__dirname,'fixtures/game-import-app-ui.jsx')],bundle:true,
      outfile:path.join(root,'app.js'),platform:'browser',format:'iife',loader:{'.png':'dataurl'},
      alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},
      define:{__MODAGENT_SUBSCRIPTION__:'false',__MODAGENT_VERSION__:'"test"','import.meta.env':'{}','process.env.NODE_ENV':'"test"'},
      plugins:[{name:'isolate-unrelated-pages',setup(build){
        build.onResolve({filter:/^\.\/components\//},args=>args.importer.endsWith('App.jsx')&&!args.path.endsWith('.mjs')&&!['./components/ChatPage','./components/Toast'].includes(args.path)?{path:args.path,namespace:'stub'}:null)
        build.onLoad({filter:/.*/,namespace:'stub'},()=>({contents:'export default function Stub(){return null}',loader:'js'}))
      }}]})
    fs.writeFileSync(path.join(root,'index.html'),'<meta charset="utf-8"><div id="root"></div><script src="app.js"></script>')
    const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:45000,windowsHide:true})
    process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');if(r.error)throw r.error;process.exit(r.status??1)
  })().catch(e=>{console.error(e);process.exit(1)})
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,width:1500,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for(const mode of ['success','rejected','recovery','timeout']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,30))}throw Error('UI timeout: '+mode+' '+fn.toString()+' '+document.body.textContent.slice(-1600))}
          const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
          const text=()=>document.body.textContent
          const dialog=()=>document.querySelector('[role=dialog]')
          await wait(()=>button('Import game'));button('Import game').click()
          await wait(()=>button('Choose folder'));button('Choose folder').click()
          await wait(()=>button('Import and switch')&&!button('Import and switch').disabled)
          const original=dialog()
          button('Import and switch').click()
          await wait(()=>window.releaseImport&&text().includes('Saving and verifying'))
          if(dialog()!==original||!original.closest('[inert]'))throw Error('Import form unmounted or unlocked during save')
          window.releaseImport()
          if(mode==='rejected'){
            await wait(()=>text().includes('GAME_IMPORT_REJECTED'))
            if(dialog()!==original||original.closest('[inert]')||![...original.querySelectorAll('input')].some(i=>i.value==='X:/New'))throw Error('Rejected import lost form or stayed locked')
            window.fixture.retry=true
            window.releaseImport=null
            button('Import and switch').click()
            await wait(()=>window.releaseImport);window.releaseImport()
          }
          if(mode==='timeout'){
            await wait(()=>text().includes('GAME_IMPORT_UNCONFIRMED'))
            if(dialog()!==original||!original.closest('[inert]')||window.fixture.writes!==1||button('Recheck active game'))throw Error('Unacknowledged import permits unsafe retry')
            return
          }
          if(mode==='recovery'){
            await wait(()=>button('Recheck active game'))
            window.fixture.recovered=true
            button('Recheck active game').click()
            await wait(()=>!text().includes('GAME_SELECTION_UNCONFIRMED'))
            if(window.fixture.writes!==1)throw Error('Read-only recovery repeated import')
            await wait(()=>!dialog())
            await wait(()=>text().includes('Scan completed: 3 detected, 2 added'))
            if(window.fixture.scanReads!==1||window.fixture.writes!==1)throw Error('Recovery repeated writes or lost scan observation')
            return
          }
          await wait(()=>!dialog())
          await wait(()=>text().includes('Scan completed: 3 detected, 2 added'))
          if(window.fixture.scanReads!==1||window.fixture.writes!==(mode==='rejected'?2:1))throw Error('Import/scan request count incorrect')
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    for(const result of results)console.log(JSON.stringify(result))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
