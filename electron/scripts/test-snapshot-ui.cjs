const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-snapshot-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/snapshot-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"test"'}})
  fs.writeFileSync(path.join(root,'index.html'),'<html><meta charset="utf-8"><body><div id="root"></div><script src="app.js"></script></body></html>')
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
for(const mode of ['restore-audit-pending','restore-inventory-pending','restore-workshop-unavailable','restore-preview-config-invalid','restore-preview-workshop-invalid','restore-preview-flag-invalid','list-label-object','list-count-object','list-bool-string','list-duplicate','restore-workshop-valid','restore-count-invalid','restore-id-invalid','restore-workshop-invalid','create-late-success','create-late-error','restore-late-success','restore-late-error','delete-late-success','delete-late-error','valid','http','body','invalid','restore-valid','restore-http','restore-body','restore-invalid','restore-preview-invalid','delete-valid','delete-http','delete-body','delete-invalid','delete-preview-invalid','restore-switch','delete-switch','restore-warnings','list-http','list-body','list-invalid','list-empty','list-loading','list-refresh']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Snapshot condition failed '+mode)}
          const original=setTimeout.bind(window)
          window.setTimeout=(fn,ms,...args)=>original(fn,[120000,15000].includes(ms)?150:ms,...args)
          const button=()=>[...document.querySelectorAll('button')].find(b=>/Create snapshot/i.test(b.textContent))
          await wait(button)
          if(mode.includes('-late-')){
            if(mode.startsWith('create-'))button().click()
            else{
              const restore=mode.startsWith('restore-')
              const entry=()=>document.querySelector('button[title="'+(restore?'Restore':'Delete')+'"]')
              await wait(entry);entry().click()
              const confirm=()=>[...document.querySelectorAll('button')].find(b=>b.textContent===(restore?'Confirm restore':'Delete'))
              await wait(confirm);confirm().click()
            }
            await wait(()=>window.fixture.finish)
            window.fixture.switchGame()
            await wait(()=>document.querySelector('[data-game="otherfixture"]'))
            const count=window.fixture.toasts.length
            window.fixture.finish()
            await wait(()=>!button().disabled)
            if(window.fixture.toasts.length!==count)throw Error('Old snapshot operation leaked feedback into new game')
            return
          }
          if(mode.startsWith('list-')){
            const content=()=>document.body.textContent
            if(mode==='list-refresh'){
              await wait(()=>content().includes('snap-recovered'))
              const refresh=[...document.querySelectorAll('button')].find(b=>/Refresh/i.test(b.textContent))
              if(!refresh)throw Error('Missing refresh button')
              refresh.click()
            }
            if(mode==='list-loading'){
              await wait(()=>window.fixture.resolve)
              if(!content().includes('Loading snapshots')||content().includes('No snapshots recorded'))throw Error('Loading mistaken for empty')
              window.fixture.resolve()
            }
            if(mode==='list-empty'||mode==='list-loading'){
              await wait(()=>content().includes('No snapshots recorded'))
              if(document.querySelector('[role="alert"]'))throw Error('Successful empty list marked failed')
              return
            }
            await wait(()=>document.querySelector('[role="alert"]'))
            if(document.querySelector('button[title="Restore"]'))throw Error('Stale snapshot actions exposed after failed refresh')
            if(content().includes('No snapshots recorded')||!content().includes('does not mean your backups are missing'))throw Error('Failure mistaken for missing backups')
            const retry=[...document.querySelectorAll('button')].find(b=>b.textContent==='Retry')
            if(!retry)throw Error('No recovery action')
            retry.click()
            await wait(()=>content().includes('snap-recovered'))
            if(!content().includes('SNAPSHOT_STORAGE_UNAVAILABLE')||content().includes('Exclusive data: ~0 B'))throw Error('Unknown storage represented as zero')
            if(document.querySelector('[role="alert"]')||window.fixture.listReads!==(mode==='list-refresh'?3:2)||window.fixture.writes||window.fixture.creates)throw Error('Retry failed or caused mutation')
            return
          }
          if(mode.startsWith('restore-')||mode.startsWith('delete-')){
            const restore=mode.startsWith('restore-')
            const entry=()=>document.querySelector('button[title="'+(restore?'Restore':'Delete')+'"]')
            await wait(entry)
            entry().click()
            const confirm=()=>[...document.querySelectorAll('button')].find(b=>b.textContent===(restore?'Confirm restore':'Delete'))
            if(mode.endsWith('switch')){
              if(!restore){await wait(confirm);confirm().click()}
              await wait(()=>window.fixture.resolve)
              window.fixture.switchGame()
              await wait(()=>document.querySelector('[data-game="otherfixture"]'))
              window.fixture.resolve()
              await wait(()=>!button().disabled)
              if(confirm()||window.fixture.writes)throw Error('Old game response leaked confirmation or write')
              return
            }
            if(mode.startsWith('restore-preview-')&&mode.endsWith('invalid')){
              await wait(()=>window.fixture.toasts.some(t=>t.includes('SNAPSHOT_PREVIEW_FAILED')))
              if(confirm()||window.fixture.writes)throw Error('Invalid preview permitted restore')
              return
            }
            await wait(confirm)
            if(mode==='restore-workshop-unavailable'){
              if(!confirm().disabled||!document.body.textContent.includes('SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE'))throw Error('Unknown workshop scope not blocked')
              confirm().click()
              if(window.fixture.writes)throw Error('Blocked workshop preview wrote')
              return
            }
            if(mode==='restore-warnings'){
              const content=document.body.textContent
              for(const phrase of ['Open mode:','saves or personal files','Documents/AppData','snapshot files are missing','changes your Steam subscriptions','within the snapshot scope'])if(!content.includes(phrase))throw Error('Missing English risk disclosure: '+phrase)
              if(/[\\u4e00-\\u9fff]/.test(content))throw Error('Untranslated fixed text in English preview')
              const cancel=[...document.querySelectorAll('button')].find(b=>b.textContent==='Cancel')
              cancel.click()
              await new Promise(r=>setTimeout(r,30))
              if(confirm()||window.fixture.writes)throw Error('Cancel triggered restore')
              return
            }
            const target=confirm();target.click();target.click()
            if(mode==='restore-inventory-pending'||mode==='restore-audit-pending'){
              await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='restore-audit-pending'?'SNAPSHOT_RECEIPT_NOT_SAVED':'SNAPSHOT_INVENTORY_PENDING')))
              await wait(()=>!button().disabled)
              if(window.fixture.toasts.some(t=>t.includes('Restored and verified')))throw Error('Inventory failure reported success')
              if(!window.fixture.toasts.some(t=>t.includes(mode==='restore-audit-pending'?'Do not assume':'preview and confirm')))throw Error('Missing safe retry guidance')
              if(window.fixture.writes!==1)throw Error('Duplicate restore')
              return
            }
            const code=restore?'SNAPSHOT_RESTORE_UNCONFIRMED':'SNAPSHOT_DELETE_UNCONFIRMED'
            await wait(()=>window.fixture.toasts.some(t=>mode.endsWith('valid')&&!mode.endsWith('invalid')
              ? t.includes(restore?'Restored and verified':'Snapshot deleted.') : t.includes(code)))
            await wait(()=>!button().disabled)
            if(window.fixture.writes!==(mode==='delete-preview-invalid'?0:1))throw Error('Wrong write count / duplicate request')
            if(mode==='restore-workshop-valid'&&!window.fixture.toasts.some(t=>t.includes('SNAPSHOT_WORKSHOP_PENDING')))throw Error('Manual Steam recovery not disclosed')
            if(mode==='restore-workshop-valid'&&!window.fixture.toasts.some(t=>t.includes('snapshot files only')))throw Error('File success implies subscription success')
            if(!mode.endsWith('valid')||mode.endsWith('invalid')){
              if(window.fixture.toasts.some(t=>t.includes('Restored and verified')||t.includes('Snapshot deleted.')))throw Error('False mutation success')
              if(!window.fixture.toasts.some(t=>t.includes('may already have changed')&&t.includes('before retrying')))throw Error('Unknown snapshot result invites blind retry')
            }
            return
          }
          const create=button();create.click();create.click()
          await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='valid'?'Snapshot created: saved-fixture':'SNAPSHOT_CREATE_UNCONFIRMED')))
          await wait(()=>!button().disabled)
          if(window.fixture.creates!==1)throw Error('Duplicate create request')
          if(mode!=='valid'&&window.fixture.toasts.some(t=>t.includes('Snapshot created:')))throw Error('False success')
          if(mode!=='valid'&&!window.fixture.toasts.some(t=>t.includes('may already have changed')&&t.includes('before retrying')))throw Error('Missing mutation uncertainty')
        })()`)
        results.push({mode,passed:true})
      }catch(error){results.push({mode,passed:false,error:error.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(result=>console.log(JSON.stringify(result)))
    win.destroy();app.exit(results.every(result=>result.passed)?0:1)
  }).catch(error=>{console.error(error);app.exit(1)})
}
