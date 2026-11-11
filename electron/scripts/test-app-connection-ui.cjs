const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-app-connection-ui')
if(!process.versions.electron){
  ;(async()=>{
  fs.mkdirSync(root,{recursive:true})
  await require('esbuild').build({entryPoints:[path.join(__dirname,'fixtures/app-connection-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"test"'},plugins:[{name:'isolate-shell',setup(build){
    build.onResolve({filter:/^\.\/components\//},args=>args.importer.endsWith('App.jsx')&&!args.path.endsWith('.mjs')?{path:args.path,namespace:'shell-fixture'}:null)
    build.onResolve({filter:/^@edition$/},()=>({path:'edition',namespace:'shell-fixture'}))
    build.onLoad({filter:/.*/,namespace:'shell-fixture'},args=>({contents:args.path==='edition'?'export const applyEditionDefaultBackground=()=>{}':args.path.endsWith('/ChatPage')?`import React from 'react'; export default function Chat(props){window.fixture.currentStatus=props.status; window.fixture.selectGame=props.onGameChange; window.fixture.importGame=props.onGameImport; return React.createElement('div',null,'ChatPage',React.createElement('textarea',{'data-testid':'draft',defaultValue:''}))}`:`export default function Component(){return ${JSON.stringify(args.path.split('/').at(-1))}}`,loader:'js',resolveDir:path.resolve(__dirname,'..')}))
  }}]})
  fs.writeFileSync(path.join(root,'index.html'),'<html><meta charset="utf-8"><body><div id="root"></div><script src="app.js"></script></body></html>')
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:30000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
  })().catch(e=>{console.error(e);process.exit(1)})
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for(const mode of ['configured','unconfigured','status-http','status-invalid','status-body','reconnect-draft','counts-http','counts-invalid','counts-body','select-valid','select-http','select-invalid','select-body','select-mismatch','import-valid','import-rejected','import-http','import-invalid','import-body','import-mismatch','select-recovery','select-recovery-retry','import-recovery']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const text=()=>document.body.textContent
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20))}throw Error('Shell did not recover '+mode)}
          if(mode.startsWith('status-')){
            await wait(()=>text().includes('APP_CONNECTION_FAILED'))
            if(text().includes('SetupPage'))throw Error('Failed status entered setup')
            await wait(()=>text().includes('ChatPage'))
            if(text().includes('APP_CONNECTION_FAILED'))throw Error('Stale connection error')
          }else await wait(()=>text().includes(mode==='unconfigured'?'SetupPage':'ChatPage'))
          if(mode==='reconnect-draft'){
            const draft=document.querySelector('[data-testid=draft]')
            draft.value='keep my unfinished question'
            window.fixture.offline=true
            await wait(()=>text().includes('APP_CONNECTION_FAILED'))
            if(document.querySelector('[data-testid=draft]')!==draft||draft.value!=='keep my unfinished question')throw Error('Draft unmounted on disconnect')
            if(!draft.closest('[inert]'))throw Error('Offline controls not locked')
            window.fixture.offline=false
            await wait(()=>!text().includes('APP_CONNECTION_FAILED'))
            if(document.querySelector('[data-testid=draft]')!==draft||draft.value!=='keep my unfinished question'||draft.closest('[inert]'))throw Error('Draft lost or locked after recovery')
          }
          if(mode.startsWith('counts-')){
            await wait(()=>window.fixture.currentStatus?.snaps===0)
            if(window.fixture.currentStatus.mods!==null)throw Error('Failed count reported as zero')
          }
          if(mode.startsWith('select-')){
            const game={name:'New Game',slug:'new-game',path:'C:/fixture/new',game_instance_id:'new-instance'}
            const pending=window.fixture.selectGame(game)
            window.fixture.selectGame(game)
            await wait(()=>window.fixture.releaseSelection)
            if(window.fixture.currentStatus.game==='New Game')throw Error('Optimistic game switch before acknowledgement')
            if(window.fixture.gameWrites!==1)throw Error('Duplicate game writes')
            window.fixture.releaseSelection()
            const success=await pending
            if(mode==='select-valid'){
              await wait(()=>window.fixture.currentStatus.game==='New Game')
              if(!success||document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Successful selection still locked')
            }else{
              await wait(()=>text().includes('GAME_SELECTION_UNCONFIRMED'))
              if(success||window.fixture.currentStatus.game==='New Game')throw Error('Unconfirmed selection reported success')
              if(!document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Uncertain game allows writes')
              await window.fixture.selectGame(game)
              if(window.fixture.gameWrites!==1)throw Error('Uncertain selection retried blindly')
            }
          }
          if(mode.startsWith('import-')){
            const pending=window.fixture.importGame({game_root:'C:/fixture/import',game_name:'Imported Game'}).catch(e=>e)
            await window.fixture.importGame({}).catch(()=>{})
            const result=await pending
            await new Promise(r=>setTimeout(r,40))
            if(mode==='import-valid'){
              if(!result.saved||window.fixture.currentStatus.game!=='Imported Game')throw Error('Confirmed import not applied')
              if(document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Imported game remains locked')
            }else if(mode==='import-rejected'){
              if(!result.message.includes('GAME_IMPORT_REJECTED')||document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Rejected input cannot be corrected')
            }else{
              if(!result.message.includes('GAME_IMPORT_UNCONFIRMED')||!text().includes('GAME_SELECTION_UNCONFIRMED'))throw Error('Uncertain import not explained')
              if(!document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Uncertain import permits writes')
            }
            if(window.fixture.gameWrites!==1)throw Error('Duplicate game import')
          }
          const recheck=()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Recheck active game')
          if(mode==='select-mismatch'||mode==='import-mismatch'){
            await wait(recheck)
            const before=window.fixture.statusReads
            recheck().click()
            await wait(()=>window.fixture.statusReads>before)
            await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))
            await wait(()=>recheck()&&!recheck().disabled)
            if(!text().includes('GAME_SELECTION_UNCONFIRMED')||!document.querySelector('[data-testid=draft]').closest('[inert]')||window.fixture.gameWrites!==1)throw Error('Mismatched recovery bypassed game lock')
          }
          if(mode.includes('recovery')){
            await wait(recheck)
            const target=recheck();target.click();target.click()
            if(mode.endsWith('retry')){
              await wait(()=>window.fixture.recoveryReads===2)
              await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))
              await wait(()=>recheck()&&!recheck().disabled)
              if(!document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Failed recheck unlocked writes')
              recheck().click()
            }
            await wait(()=>!text().includes('GAME_SELECTION_UNCONFIRMED'))
            const expected=mode.startsWith('import-')?'Imported Game':'New Game'
            if(window.fixture.currentStatus.game!==expected||document.querySelector('[data-testid=draft]').closest('[inert]'))throw Error('Verified game not recovered')
            if(window.fixture.gameWrites!==1||window.fixture.recoveryReads!==(mode.endsWith('retry')?3:2))throw Error('Recovery duplicated write or read')
          }else if(['select-http','select-body','select-invalid','import-http','import-body','import-invalid'].includes(mode)&&recheck())throw Error('Unacknowledged write offered unsafe recovery')
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.mode+(r.error?' '+r.error:'')))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
