const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-settings-save-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/settings-save-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',loader:{'.png':'dataurl'},alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},define:{__MODAGENT_SUBSCRIPTION__:'false',__MODAGENT_VERSION__:'"fixture"','import.meta.env':'{}','process.env.NODE_ENV':'"test"'}})
  fs.writeFileSync(path.join(root,'index.html'),'<html><meta charset="utf-8"><body><div id="root"></div><script src="app.js"></script></body></html>')
  const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:45000,windowsHide:true})
  process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'')
  if(r.error)throw r.error
  process.exit(r.status??1)
}else{
  const {app,BrowserWindow,session}=require('electron')
  app.setPath('userData',path.join(root,'profile'))
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}))
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}})
    const results=[]
    for(const mode of ['background-valid','background-error','background-preview-invalid','background-remove-invalid','success','credential-error','credential-timeout','config-http','config-body','config-invalid','load-http','load-body','load-invalid','share-valid','share-http','share-body','share-invalid','export-valid','export-cancel','export-disk','export-invalid','export-body','catalog-valid','catalog-cache','catalog-empty','catalog-invalid','catalog-body','diagnostics-invalid','diagnostics-empty','official-valid','official-mismatch','official-empty','official-prerequisite','report-valid','report-cancel','report-error','report-invalid','maintenance-open-error','maintenance-missing','maintenance-timeout','maintenance-copy','update-disabled','update-invalid','update-timeout','update-available','update-current']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Settings did not recover: '+mode)}
          const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
          if(mode.startsWith('load-')){
            await wait(()=>button('Retry loading settings'))
            if(!document.body.textContent.includes('SETTINGS_LOAD_FAILED'))throw Error('Load error missing')
            if(button('Save settings')||document.querySelector('input[type=password]'))throw Error('Default settings editable after load failed')
            if(window.fixture.stores||window.fixture.requests.some(r=>r.url.endsWith('/config')))throw Error('Unexpected writes')
            button('Retry loading settings').click()
            await wait(()=>button('Save settings'))
            if(window.fixture.statusReads!==2)throw Error('Retry did not read settings')
            if(![...document.querySelectorAll('input')].some(i=>i.value==='https://fixture.invalid/v1'))throw Error('Existing endpoint not restored')
            return
          }
          await wait(()=>button('Save settings'))
          await new Promise(r=>setTimeout(r,60))
          if(mode.startsWith('background-')){
            if(mode==='background-error'&&!document.body.textContent.includes('Other settings remain available'))throw Error('Background read failure not explained independently');
            const remove=mode==='background-remove-invalid'
            const target=button(remove?'Remove background':'Change background');target.click();target.click()
            const expected=mode==='background-valid'?'Background updated.':remove?'BACKGROUND_REMOVE_FAILED':'BACKGROUND_CHANGE_FAILED'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(expected)))
            await wait(()=>!button('Change background').disabled)
            if(window.fixture.backgroundCalls!==1)throw Error('Duplicate background mutation')
            if(window.fixture.toasts.some(t=>t.includes('private source')))throw Error('Private path leaked')
            if(mode!=='background-valid'&&window.fixture.toasts.some(t=>t.includes('Background updated.')||t.includes('Custom background removed.')))throw Error('False background success')
            return
          }
          if(mode.startsWith('update-')){
            const target=button('Check for updates');target.click();target.click()
            const expected={'update-disabled':'Updates are disabled','update-invalid':'UPDATE_CHECK_FAILED','update-timeout':'UPDATE_TIMEOUT','update-available':'Version 1.7.0 is available','update-current':'No newer version was reported'}[mode]
            await wait(()=>window.fixture.toasts.some(t=>t.includes(expected)))
            await wait(()=>!button('Check for updates').disabled)
            if(window.fixture.updateCalls!==1)throw Error('Duplicate update check')
            if(mode!=='update-current'&&window.fixture.toasts.some(t=>t.includes('No newer version')))throw Error('False up-to-date result')
            return
          }
          if(mode.startsWith('maintenance-')){
            const label=mode==='maintenance-copy'?'Copy log folder path':'Open logs'
            const target=button(label);target.click()
            if(mode!=='maintenance-missing')target.click()
            const expected=mode==='maintenance-copy'?'Log folder path copied.':mode==='maintenance-timeout'?'MAINTENANCE_TIMEOUT':mode==='maintenance-missing'?'MAINTENANCE_UNAVAILABLE':'MAINTENANCE_FAILED'
            await wait(()=>window.fixture.toasts.some(t=>t.includes(expected)))
            await wait(()=>!button(label).disabled)
            if((window.fixture.maintenanceCalls||0)!==(mode==='maintenance-missing'?0:1))throw Error('Duplicate maintenance action')
            if(window.fixture.toasts.some(t=>t.includes('private folder')))throw Error('Raw OS error leaked')
            return
          }
          if(mode.startsWith('report-')){
            const target=button('Export diagnostics');target.click();target.click()
            await wait(()=>button('Finish the export dialog…'))
            if(!button('Finish the export dialog…').disabled)throw Error('Export control not locked')
            await wait(()=>button('Export diagnostics')&&!button('Export diagnostics').disabled)
            if(window.fixture.diagnosticCalls!==1||window.fixture.diagnosticLanguage!=='en')throw Error('Duplicate export or wrong language')
            if(mode==='report-cancel'){
              if(window.fixture.toasts.length)throw Error('Cancel reported success or failure')
            }else{
              const expected=mode==='report-valid'?'Diagnostics exported':'DIAGNOSTICS_EXPORT_FAILED'
              if(!window.fixture.toasts.some(t=>t.includes(expected)))throw Error('Wrong export outcome')
              if(window.fixture.toasts.some(t=>t.includes('private path')))throw Error('Private exception leaked')
            }
            return
          }
          if(mode.startsWith('official-')){
            button('浏览').click()
            await wait(()=>button('打开'))
            const open=button('打开');open.click();open.click()
            await wait(()=>window.fixture.toasts.length)
            if(mode==='official-mismatch'){
              if(!window.fixture.toasts.some(t=>t.includes('SETTINGS_SHARE_FAILED')))throw Error('Mismatched collection accepted')
              if(button('在聊天中继续核验官方合集'))throw Error('Mismatched plan enabled')
            }else if(mode==='official-empty'){
              if(button('在聊天中继续核验官方合集')||button('Review prerequisites in chat'))throw Error('Empty collection permits plan')
            }else{
              const prerequisite=mode==='official-prerequisite'
              button(prerequisite?'Review prerequisites in chat':'在聊天中继续核验官方合集').click()
              const plan=window.fixture.plans[0]
              if(plan.shareId!=='ma-fixture'||plan.action!==(prerequisite?'prerequisite_plan':'install_plan'))throw Error('Incorrect collection/action passed to chat')
            }
            if(window.fixture.requests.filter(r=>r.url.endsWith('/tool/official_share_import')).length!==1)throw Error('Duplicate collection requests')
            return
          }
          if(mode.startsWith('catalog-')||mode.startsWith('diagnostics-')){
            const isCatalog=mode.startsWith('catalog-')
            const trigger=button(isCatalog?'浏览':'网络诊断')
            trigger.click();trigger.click()
            if(['catalog-valid','catalog-cache'].includes(mode)){
              await wait(()=>document.body.textContent.includes('Fixture collection'))
              if(mode==='catalog-cache'&&!window.fixture.toasts.some(t=>t.includes('缓存')))throw Error('Cache fallback not identified')
            }else if(mode==='catalog-empty'){
              await wait(()=>document.body.textContent.includes('暂无匹配的官方合集'))
              if(window.fixture.toasts.some(t=>t.includes('无法读取')))throw Error('Reachable empty catalog called unavailable')
            }else{
              const code=isCatalog?'OFFICIAL_CATALOG_FAILED':mode==='diagnostics-empty'?'OFFICIAL_CHECK_EMPTY':'OFFICIAL_CHECK_FAILED'
              await wait(()=>window.fixture.toasts.some(t=>t.includes(code)))
              if(document.body.textContent.includes('Fixture collection'))throw Error('Invalid catalog rendered')
            }
            if(trigger.disabled)throw Error('Official action remained locked')
            if(window.fixture.requests.filter(r=>r.url.includes('/tool/official_share_')).length!==1)throw Error('Duplicate official requests')
            return
          }
          if(mode.startsWith('export-')){
            const exportButton=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('导出配置 JSON'))
            exportButton.click();exportButton.click()
            await wait(()=>window.fixture.toasts.length)
            const messages=window.fixture.toasts.join(' ')
            if(mode==='export-valid'){
              if(!messages.includes('Configuration JSON saved'))throw Error('Save not acknowledged')
              if(JSON.parse(window.fixture.saves[0].text).mods.length!==1)throw Error('Export content changed')
            }else{
              if(messages.includes('Configuration JSON saved'))throw Error('Unconfirmed save claimed success')
              const expected=mode==='export-cancel'?'Save cancelled':mode==='export-disk'?'SETTINGS_SHARE_SAVE_FAILED':'SETTINGS_SHARE_FAILED'
              if(!messages.includes(expected))throw Error('Missing export outcome '+expected)
            }
            const count=['export-invalid','export-body'].includes(mode)?0:1
            if(window.fixture.saves.length!==count)throw Error('Invalid content saved or duplicate saves')
            if(window.fixture.requests.filter(r=>r.url.endsWith('/tool/share_export')).length!==1)throw Error('Duplicate export request')
            if(exportButton.disabled)throw Error('Export remains locked')
            return
          }
          if(mode.startsWith('share-')){
            const input=[...document.querySelectorAll('textarea')].find(t=>t.placeholder.includes('GitHub Raw'))
            const edit=value=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}))}
            edit('fixture first share')
            await new Promise(r=>setTimeout(r,30))
            const inspect=button('解析并核验分享配置');inspect.click();inspect.click()
            if(mode==='share-valid'){
              await wait(()=>button('在聊天中继续生成安装计划'))
              edit('fixture changed share')
              await new Promise(r=>setTimeout(r,30))
              if(button('在聊天中继续生成安装计划'))throw Error('Edited input retained old preview')
              button('解析并核验分享配置').click()
              await wait(()=>button('在聊天中继续生成安装计划'))
              button('在聊天中继续生成安装计划').click()
              if(window.fixture.plans[0]!=='fixture changed share')throw Error('Plan used stale input')
            }else{
              await wait(()=>window.fixture.toasts.some(t=>t.includes('SETTINGS_SHARE_FAILED')))
              if(input.value!=='fixture first share'||input.readOnly)throw Error('Failed preview lost/locked input')
              if(button('在聊天中继续生成安装计划'))throw Error('Invalid preview enables plan')
            }
            if(window.fixture.requests.filter(r=>r.url.endsWith('/tool/share_import')).length!==(mode==='share-valid'?2:1))throw Error('Duplicate share requests')
            return
          }
          const keyField=[...document.querySelectorAll('input[type=password]')].at(-1)
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(keyField,'fake-settings-key')
          keyField.dispatchEvent(new Event('input',{bubbles:true}))
          await new Promise(r=>setTimeout(r,30))
          const save=button('Save settings');save.click();save.click()
          await wait(()=>window.fixture.toasts.length)
          if(window.fixture.stores!==1)throw Error('Duplicate secure writes')
          if(window.fixture.requests.some(r=>r.url.endsWith('/chat/reset')))throw Error('No-session reset should not run')
          const configs=window.fixture.requests.filter(r=>r.url.endsWith('/config'))
          if(configs.some(r=>r.body.includes('fake-settings-key')))throw Error('Secret resent through config')
          if(configs.length!==(mode.startsWith('credential-')?0:1))throw Error('Unexpected config requests')
          if(mode==='success'){
            if(window.fixture.toasts.some(t=>t.includes('[SETTINGS_')))throw Error('Success rejected')
            if(!button('Save settings'))throw Error('Save remained busy')
          }else{
            if(keyField.value!=='fake-settings-key')throw Error('Input lost on failure')
            const code=mode==='credential-timeout'?'SETTINGS_SAVE_UNCONFIRMED':mode==='credential-error'?'SETTINGS_CREDENTIAL_FAILED':'SETTINGS_CONFIG_FAILED'
            if(!window.fixture.toasts.some(t=>t.includes(code)))throw Error('Missing specific error '+code)
            if(mode.startsWith('config-')&&!window.fixture.toasts.some(t=>t.includes('Credentials were saved securely')))throw Error('Partial save misreported')
            if(mode==='credential-timeout'){
              if(!button('Restart to check saved state')?.disabled)throw Error('Uncertain IPC permits retry')
            }else if(button('Save settings')?.disabled!==false)throw Error('Save remained busy')
          }
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.mode+(r.error?' '+r.error:'')))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
