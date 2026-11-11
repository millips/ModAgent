const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-mod-list-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/mod-list-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{__MODAGENT_SUBSCRIPTION__:'false','import.meta.env':'{}','process.env.NODE_ENV':'"test"'}})
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
for(const mode of ['direct-cache','write-cache','write-snapshot','write-tls','source-confirm-hold','source-confirm-invalid','source-invalid-flag','source-invalid-id','source-invalid-name','source-invalid-target','folder-actions','dependency-valid','dependency-missing','dependency-cancel','dependency-switch','dependency-body','dependency-switch-error','gate-valid','gate-blocked','toggle-preview-id','toggle-preview-note','toggle-preview-external','toggle-preview-flags','toggle-empty','toggle-wrong-id','toggle-external-incomplete','toggle-duplicate','list-http','list-body','list-invalid','list-switch','reconcile-valid','reconcile-invalid','reconcile-body','cancel-valid','cancel-http','cancel-body','cancel-missing','update-name-object','update-duplicate','update-count-string','update-cancel-string','update-empty','update-partial','update-current','update-http','update-invalid','update-body','align-valid','align-http','align-invalid','align-body','write-valid','write-invalid','write-body','write-rollback','batch-success','batch-failure','batch-hang','batch-switch','batch-language','direct-valid','direct-invalid','direct-blocked','direct-body','direct-risk','toggle-valid','toggle-invalid','toggle-body','toggle-http','enable-valid','source-valid','source-http','source-body','merge-valid','merge-http','merge-body','merge-invalid','merge-switch']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Mod list condition failed '+mode)}
          const original=setTimeout.bind(window)
          window.setTimeout=(fn,ms,...args)=>original(fn,[120000,15000].includes(ms)?150:ms,...args)
          if(mode==='folder-actions'){
            for(const kind of ['dropbox','downloads','tools'])for(const result of ['invalid','false','http','body','valid']){
              const target=()=>document.querySelector('[data-folder-kind="'+kind+'"]')
              await wait(()=>target()&&!target().disabled)
              const before=window.fixture.folderCalls||0, start=window.fixture.toasts.length
              window.fixture.folderMode=result
              const b=target();b.click();b.click()
              await wait(()=>window.fixture.toasts.length>start)
              await wait(()=>!target().disabled)
              if(window.fixture.folderCalls!==before+1)throw Error('Duplicate folder request')
              const messages=window.fixture.toasts.slice(start).join(' ')
              if(messages.includes('PRIVATE_FIXTURE')||/[\\u4e00-\\u9fff]/.test(messages))throw Error('Unsafe/untranslated folder feedback')
              if(result==='valid'){
                if(!messages.includes('Folder opening requested'))throw Error('Missing truthful folder acknowledgement')
              }else if(!messages.includes('FOLDER_OPEN_UNCONFIRMED')||messages.includes('Folder opening requested'))throw Error('False folder success')
            }
            return
          }
          if(mode.startsWith('dependency-')){
            const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
            const dialog=()=>document.querySelector('[role="dialog"]')
            await wait(()=>document.querySelector('button[title="Enable"]'))
            document.querySelector('button[title="Enable"]').click()
            await wait(dialog)
            if(window.fixture.toggleArgs.length!==1||window.fixture.toggleArgs[0].confirmed)throw Error('Preview changed authorization')
            if(mode==='dependency-missing'){
              if(button('Enable dependencies and continue')||!dialog().innerText.includes('Required library'))throw Error('Missing dependency gate incorrect')
              button('Got it').click()
            }else if(mode==='dependency-cancel'){
              button('Cancel').click()
            }else if(mode==='dependency-switch'){
              window.fixture.switchGame()
              await wait(()=>document.body.innerText.includes('New Mod'))
            }else{
              const confirm=button('Enable dependencies and continue');confirm.click();confirm.click()
              if(mode==='dependency-switch-error'){
                await wait(()=>window.fixture.rejectToggle)
                window.fixture.switchGame()
                await wait(()=>document.body.innerText.includes('New Mod'))
                window.fixture.rejectToggle()
                await new Promise(r=>setTimeout(r,80))
                if(window.fixture.toasts.some(t=>t.includes('MOD_TOGGLE_UNCONFIRMED')))throw Error('Old game error leaked into current game')
              }else{
                await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='dependency-body'?'MOD_TOGGLE_UNCONFIRMED':'Old Mod enabled; 2 Mods processed')))
                if(mode==='dependency-body'&&!window.fixture.toasts.some(t=>t.includes('may already have changed')&&t.includes('before retrying')))throw Error('Write timeout lacks uncertainty guidance')
              }
              if(window.fixture.toggleArgs.length!==2||window.fixture.toggleArgs[1].confirmed!==true)throw Error('Missing or duplicate enable confirmation')
            }
            await wait(()=>!dialog())
            if(['dependency-missing','dependency-cancel','dependency-switch'].includes(mode)&&window.fixture.toggles!==1)throw Error('Cancelled or blocked preview wrote')
            if(mode!=='dependency-valid'&&window.fixture.toasts.some(t=>t.includes('Old Mod enabled')))throw Error('False enable success')
          }else if(mode.startsWith('gate-')){
            await wait(()=>document.querySelector('button[title="Disable"]'))
            document.querySelector('button[title="Disable"]').click()
            const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
            if(mode==='gate-blocked'){
              await wait(()=>document.body.innerText.includes('Use Steam'))
              if(button('Disable all listed'))throw Error('External manager gate offered local confirmation')
              button('Got it').click()
              if(window.fixture.toggles!==1)throw Error('Blocked gate wrote')
            }else{
              await wait(()=>button('Disable all listed'))
              const dialog=()=>document.querySelector('[role="dialog"][aria-label="Dependency operation review"]')
              if(!dialog()||/[\u3400-\u9fff]/.test(dialog().innerText))throw Error('English gate contains untranslated UI')
              window.fixture.setLanguage('zh-CN')
              await wait(()=>button('全部禁用'))
              if(!document.querySelector('[role="dialog"][aria-label="依赖操作确认"]'))throw Error('Chinese gate missing')
              window.fixture.setLanguage('en')
              await wait(()=>button('Disable all listed'))
              if(window.fixture.toggles!==1)throw Error('Preview performed confirmation')
              button('Disable all listed').click()
              await wait(()=>window.fixture.toasts.some(t=>t.includes('Old Mod disabled')))
              if(window.fixture.toggles!==2||window.fixture.toggleConfirmed.confirmation_token!=='fixture-token')throw Error('Confirmation token lost or duplicated')
            }
          }else if(mode.startsWith('merge-')){
            const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
            await wait(()=>document.body.innerText.includes('Second Mod'))
            button('Select all').click()
            await wait(()=>button('合并为 Mod 包'));button('合并为 Mod 包').click()
            await wait(()=>button('确认合并'))
            const input=document.querySelector('input[maxlength="160"]')
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Test package')
            input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,30))
            const confirm=button('确认合并');confirm.click();confirm.click()
            if(mode==='merge-switch'){
              await wait(()=>window.fixture.resolve);window.fixture.switchGame()
              await wait(()=>document.body.innerText.includes('New Mod'))
              button('Select all').click();await new Promise(r=>setTimeout(r,30))
              window.fixture.resolve();await new Promise(r=>setTimeout(r,80))
              if(!button('合并为 Mod 包')||window.fixture.toasts.some(t=>t.includes('已合并为')))throw Error('Old merge changed current game selection')
            }else{
              await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='merge-valid'?'已合并为':'MOD_PACKAGE_MERGE_UNCONFIRMED')))
              if(mode!=='merge-valid'&&input.value!=='Test package')throw Error('Merge draft lost')
            }
            if(window.fixture.merges!==1)throw Error('Duplicate merge request')
          }else if(mode.startsWith('source-')){
            await wait(()=>document.querySelector('button[title^="仅处理"]'))
            document.querySelector('button[title^="仅处理"]').click()
            const input=()=>document.querySelector('input[placeholder="Enter a source URL to check"]')
            const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent===text)
            const fill=async text=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input(),text);input().dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,30))}
            await wait(input)
            const review=()=>document.querySelector('[role="dialog"][aria-label="Review maintenance sources"]')
            if(!review()||/[\\u4e00-\\u9fff]/.test(review().textContent))throw Error('Source review not in English')
            window.fixture.setLanguage('zh-CN')
            await wait(()=>button('检查网址'))
            if(!document.querySelector('[role="dialog"]').textContent.includes('待确认')&&!document.querySelector('[role="dialog"]').textContent.includes('确认维护来源'))throw Error('Chinese review missing')
            window.fixture.setLanguage('en')
            await wait(input)
            await fill('https://www.nexusmods.com/game/mods/123')
            const check=button('Check URL');check.click();check.click()
            if(mode.startsWith('source-confirm-')){
              await wait(()=>button('Confirm link'))
              const confirm=button('Confirm link');confirm.click();confirm.click()
              await wait(()=>window.fixture.bindArgs.length===2)
              if(mode==='source-confirm-hold'){
                await wait(()=>window.releaseSourceConfirm&&button('Skip for now').disabled)
                const originalReview=review()
                const close=originalReview.querySelector('button[title="Review later"]')
                if(!close.disabled||!input().readOnly)throw Error('Pending source write permits editing or closing')
                close.click();button('Skip for now').click();originalReview.parentElement.click()
                await new Promise(r=>setTimeout(r,30))
                if(review()!==originalReview)throw Error('Pending source write dialog closed')
                window.releaseSourceConfirm()
              }else{
                await wait(()=>window.fixture.toasts.some(t=>t.includes('MOD_SOURCE_BIND_UNCONFIRMED')))
                if(!review()||input().value!=='https://www.nexusmods.com/game/mods/123')throw Error('Unconfirmed write lost source form')
                if(window.fixture.toasts.some(t=>t.includes('linked to')))throw Error('Malformed binding reported success')
                window.fixture.sourceRecovered=true
                await wait(()=>button('Confirm link')&&!button('Confirm link').disabled)
                button('Confirm link').click()
              }
              await wait(()=>!review())
              await wait(()=>window.fixture.toasts.some(t=>t.includes('linked to')))
              if(window.fixture.bindArgs.length!==(mode==='source-confirm-hold'?2:3))throw Error('Duplicate source writes')
            }else if(mode==='source-valid'){
              await wait(()=>button('Confirm link'))
              await fill('https://www.nexusmods.com/game/mods/456')
              if(button('Confirm link'))throw Error('Stale URL verification still actionable')
              button('Check URL').click()
              await wait(()=>button('Confirm link'));button('Confirm link').click()
              await wait(()=>window.fixture.bindArgs?.some(a=>a.confirmed))
              if(window.fixture.bindArgs.length!==3||window.fixture.bindArgs[2].source_key!=='456')throw Error('Duplicate or stale source bind')
            }else{
              await wait(()=>window.fixture.toasts.some(t=>t.includes('MOD_SOURCE_PREVIEW_FAILED')))
              if(button('Confirm link')||window.fixture.bindArgs.length!==1)throw Error('Failed source preview actionable')
              if(input().value!=='https://www.nexusmods.com/game/mods/123')throw Error('Failure discarded URL')
              window.fixture.sourceRecovered=true
              await wait(()=>button('Check URL')&&!button('Check URL').disabled)
              button('Check URL').click()
              await wait(()=>button('Confirm link'))
              if(window.fixture.bindArgs.length!==2||window.fixture.bindArgs.some(a=>a.confirmed))throw Error('Preview retry wrote binding')
            }
          }else if(mode.startsWith('toggle-')||mode==='enable-valid'){
            const button=()=>document.querySelector(mode==='enable-valid'?'button[title="Enable"]':'button[title="Disable"]')
            await wait(button);const target=button();target.click();target.click()
            await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='enable-valid'?'Old Mod enabled':mode==='toggle-valid'?'Old Mod disabled':'MOD_TOGGLE_UNCONFIRMED')))
            await wait(()=>!button().disabled)
            if(window.fixture.toggles!==1)throw Error('Duplicate toggle')
            if(mode!=='toggle-valid'&&window.fixture.toasts.some(t=>t.includes('Old Mod disabled')))throw Error('False toggle success')
            if(mode.startsWith('toggle-')&&mode!=='toggle-valid'&&!window.fixture.toasts.some(t=>t.includes('may already have changed')&&t.includes('before retrying')))throw Error('Toggle failure invites blind retry')
          }else if(mode.startsWith('direct-')){
            await wait(()=>document.body.innerText.includes('Old Mod'))
            const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
            button('Download mod').click()
            await wait(()=>button('Download and preview'))
            const input=document.querySelector('input[placeholder^="thunderstore.io"]')
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'https://example.com/mod')
            input.dispatchEvent(new Event('input',{bubbles:true}))
            await new Promise(r=>setTimeout(r,30))
            button('Download and preview').click()
            if(mode==='direct-invalid'){
              await wait(()=>window.fixture.toasts.some(t=>t.includes('DIRECT_DOWNLOAD_UNCONFIRMED')))
              if(window.fixture.installs)throw Error('Invalid download reached install')
              return
            }
            await wait(()=>button('Confirm installation'))
            if(window.fixture.installs)throw Error('Installed before preview confirmation')
            const confirm=button('Confirm installation');confirm.click();confirm.click()
            if(mode==='direct-risk'){
              await wait(()=>button('Accept risk and install')&&!button('Accept risk and install').disabled)
              if(window.fixture.installs!==1||window.fixture.installArgs[0].compatibility_confirmed)throw Error('Risk auto-accepted')
              if(!document.body.innerText.includes('Compatibility risk:')||!document.body.innerText.includes('Mods/fixture.dll'))throw Error('Risk or original file targets missing')
              button('Accept risk and install').click()
              await wait(()=>window.fixture.toasts.some(t=>t.includes('Installed 1 files')))
              if(window.fixture.installs!==2||window.fixture.installArgs[1].compatibility_confirmed!==true)throw Error('Second risk confirmation not forwarded')
              return
            }
            const code=mode==='direct-cache'?'ARCHIVE_CLEANUP_UNCONFIRMED':mode==='direct-valid'?'Installed 1 files':mode==='direct-blocked'?'DIRECT_INSTALL_NOT_COMPLETE':'DIRECT_INSTALL_UNCONFIRMED'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(code)))
            if(mode==='direct-cache'){
              const message=window.fixture.toasts.join(' ')
              if(!message.includes('Installed 1 files')||!message.includes('do not reinstall')||message.includes('PRIVATE')||message.includes('DIRECT_INSTALL_NOT_COMPLETE'))throw Error('Cache maintenance invalidated successful installation')
            }
            if(window.fixture.installs!==1)throw Error('Duplicate direct install')
            if(!['direct-valid','direct-cache'].includes(mode)&&window.fixture.toasts.some(t=>t.includes('Installed 1 files')))throw Error('Blocked install reported success')
          }else if(mode.startsWith('batch-')){
            await wait(()=>document.body.innerText.includes('Old Mod'))
            document.querySelector('button[title="Check versions, then select updates to apply"]').click()
            const confirm=()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Update selected 3')
            await wait(confirm)
            if(/[\\u4e00-\\u9fff]/.test(document.querySelector('[role="dialog"]').textContent))throw Error('Chinese update review in English mode')
            if(window.fixture.writes)throw Error('Update started without confirmation')
            if(mode==='batch-language'){
              document.querySelector('[role="dialog"] input[type="checkbox"]').click()
              window.fixture.setLanguage('zh-CN')
              const selected=()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='更新所选 2 项')
              await wait(selected)
              if(document.querySelectorAll('[role="dialog"] input:checked').length!==2)throw Error('Language switch lost selection')
              window.fixture.setLanguage('en')
              await wait(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='Update selected 2'))
              const later=[...document.querySelectorAll('button')].find(b=>b.textContent==='Update later');later.click()
              await wait(()=>!document.querySelector('[role="dialog"]'))
              if(window.fixture.writes)throw Error('Language or dismiss triggered update')
              return
            }
            const btn=confirm();btn.click();btn.click()
            if(mode==='batch-switch'){
              await wait(()=>window.fixture.resolve)
              window.fixture.switchGame()
              await wait(()=>document.body.innerText.includes('New Mod'))
              window.fixture.resolve()
            }
            const expected=mode==='batch-success'?'Confirmed updates: 3':mode==='batch-switch'?'2 not started after switching games':'1 confirmed, 1 failed or unconfirmed, 1 not started'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(expected)))
            if(['update-name-object','update-duplicate','update-count-string','update-cancel-string'].includes(mode)){
              if(document.querySelector('[role="dialog"]')||window.fixture.writes)throw Error('Malformed response exposed update execution')
              if(window.fixture.toasts.some(t=>t.includes('Update check cancelled')||t.includes('No updates found')))throw Error('Malformed response reported successful outcome')
            }
            const ids=window.fixture.ids.join(',')
            if(ids!==(mode==='batch-success'?'a,b,c':mode==='batch-switch'?'a':'a,b'))throw Error('Unexpected batch writes: '+ids)
          }else if(mode.startsWith('write-')){
            await wait(()=>document.body.innerText.includes('Old Mod'))
            document.querySelector('button[title="Check versions, then select updates to apply"]').click()
            const update=()=>document.querySelector('button[title="Update"]')
            await wait(update);const btn=update();btn.click();btn.click()
            const code=mode==='write-cache'?'UPDATE_CACHE_CLEANUP_UNCONFIRMED':mode==='write-snapshot'?'UPDATE_SNAPSHOT_FAILED':mode==='write-tls'?'UPDATE_SOURCE_FAILED':mode==='write-valid'?'Old Mod updated':mode==='write-rollback'?'MOD_UPDATE_RECOVERY_REQUIRED':'MOD_UPDATE_UNCONFIRMED'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(code)))
            if(mode==='write-cache'){
              const message=window.fixture.toasts.join(' ')
              if(!message.includes('Old Mod updated')||!message.includes('do not repeat the update')||message.includes('PRIVATE')||message.includes('MOD_UPDATE_UNCONFIRMED'))throw Error('Cache warning misreported update result')
            }
            if(mode==='write-snapshot'){
              const message=window.fixture.toasts.join(' ')
              if(!message.includes('old version was not removed')||!message.includes('disk space')||message.includes('PRIVATE'))throw Error('Unsafe or unclear snapshot feedback')
            }
            if(mode==='write-tls'){
              const message=window.fixture.toasts.join(' ')
              if(!message.includes('Certificate verification failed')||!message.includes('old version is unchanged')||message.includes('PRIVATE'))throw Error('Unsafe or unclear TLS feedback')
            }
            await wait(()=>!update()||!update().disabled)
            if(window.fixture.writes!==1)throw Error('Duplicate update write')
            if(!['write-valid','write-cache'].includes(mode)&&window.fixture.toasts.some(t=>t.includes('Old Mod updated')))throw Error('False update success')
          }else if(mode.startsWith('update-')||mode.startsWith('align-')){
            await wait(()=>document.body.innerText.includes('Old Mod'))
            const align=mode.startsWith('align-')
            const entry=()=>document.querySelector(align?'button[title^="仅处理"]':'button[title="Check versions, then select updates to apply"]')
            await wait(entry);entry().click()
            const code=align?'MOD_ALIGNMENT_UNCONFIRMED':'MOD_UPDATE_CHECK_UNCONFIRMED'
            const expected=mode==='update-partial'?'1 succeeded, 1 unavailable':mode==='update-current'?'limited to the sources checked':mode==='update-empty'?'does not mean all Mods are up to date':mode==='align-valid'?'对齐完成':code
            await wait(()=>window.fixture.toasts.some(t=>t.includes(expected)))
            if(!align&&window.fixture.toasts.some(t=>/[\\u4e00-\\u9fff]/.test(t)))throw Error('Chinese update outcome in English mode')
            await wait(entry)
            if(mode!=='align-valid'&&window.fixture.toasts.some(t=>t.includes('均为最新')||t.includes('对齐完成')))throw Error('False source success')
          }else if(mode.startsWith('cancel-')){
            const start=()=>document.querySelector('button[title="Check versions, then select updates to apply"]')
            await wait(start);start().click()
            const stop=()=>document.querySelector('button[title="Cancel this update check"]')
            await wait(stop);stop().click()
            const code=mode==='cancel-valid'?'TASK_CANCEL_REQUESTED':mode==='cancel-missing'?'TASK_CANCEL_UNCONFIRMED':'TASK_CANCEL_FAILED'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(code)))
            await wait(start)
            if(window.fixture.toasts.some(t=>t.startsWith('Update check cancelled')))throw Error('Frontend abort misreported backend cancellation')
          }else if(mode==='list-switch'){
            await wait(()=>window.fixture.resolve)
            window.fixture.switchGame()
            await wait(()=>document.body.innerText.includes('New Mod'))
            window.fixture.resolve()
            await new Promise(r=>setTimeout(r,80))
            if(document.body.innerText.includes('Old Mod')||!document.body.innerText.includes('New Mod'))throw Error('Late old game overwrote inventory')
          }else if(mode.startsWith('list-')){
            await wait(()=>window.fixture.toasts.some(t=>t.includes('MOD_LIST_FAILED')))
          }else{
            await wait(()=>document.body.innerText.includes('Old Mod'))
            const btn=[...document.querySelectorAll('button')].find(b=>b.getAttribute('title')?.includes('磁盘'))
            if(!btn)throw Error('Reconcile button missing')
            btn.click();btn.click()
            await wait(()=>window.fixture.toasts.some(t=>t.includes(mode==='reconcile-valid'?'对账完成':'MOD_RECONCILE_UNCONFIRMED')))
            if(window.fixture.reconciles!==1)throw Error('Duplicate reconciliation')
            if(mode!=='reconcile-valid'&&window.fixture.toasts.some(t=>t.includes('对账完成')))throw Error('Invalid receipt reported success')
          }
        })()`)
        results.push({mode,passed:true})
      }catch(error){results.push({mode,passed:false,error:error.message,fixture:await win.webContents.executeJavaScript('JSON.stringify(window.fixture)')})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(result=>console.log(JSON.stringify(result)))
    win.destroy();app.exit(results.every(result=>result.passed)?0:1)
  }).catch(error=>{console.error(error);app.exit(1)})
}
