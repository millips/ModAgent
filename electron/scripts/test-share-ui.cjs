const fs=require('node:fs'),path=require('node:path')
const root=process.env.MODAGENT_UI_TEST_OUTPUT||path.resolve(__dirname,'../../build/v17-share-ui')
if(!process.versions.electron){
  fs.mkdirSync(root,{recursive:true})
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/share-ui.jsx')],bundle:true,outfile:path.join(root,'app.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"test"'}})
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
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const results=[]
for(const mode of ['en-version-different','en-version-matching','en-version-unknown','valid','import-http','import-body','import-invalid','export-valid','export-http','export-body','export-invalid','export-saveerror','export-cancel','export-diskerror','en-valid','en-prerequisite','en-included','en-empty','en-unknown','official-valid','official-mismatch','official-wrong-kind','export-page-valid','export-page-error','export-page-timeout','export-copy-valid','export-copy-error','export-copy-timeout','export-copy-empty']){
      await win.loadFile(path.join(root,'index.html'),{query:{mode}})
      // Each scenario owns its fixture records. Do not inherit submission_opened
      // from the preceding case (upserts intentionally preserve existing metadata).
      await win.webContents.executeJavaScript("localStorage.removeItem('modagent-p-share-submissions-v1')")
      try{
        await win.webContents.executeJavaScript(`(async()=>{
          const mode=${JSON.stringify(mode)}
          const wait=async(fn)=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,25))}throw Error('Share UI condition failed '+mode)}
          const timer=window.setTimeout.bind(window)
          window.setTimeout=(fn,ms,...a)=>timer(fn,[15000,20000].includes(ms)?150:ms,...a)
          const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes(text))
          const fill=async(el,value)=>{
            Object.getOwnPropertyDescriptor(el.tagName==='INPUT'?HTMLInputElement.prototype:HTMLTextAreaElement.prototype,'value').set.call(el,value)
            el.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,35))
          }
          await wait(()=>document.querySelector('input'))
          if(mode.startsWith('official-')){
            await fill(document.querySelector('input'),'MA-REPO-000002')
            button('Import and verify').click()
            if(mode==='official-valid'){
              await wait(()=>button('Create installation plan'))
              if(window.shareFixture.plans.length)throw Error('Preview auto-dispatched plan')
              button('Create installation plan').click()
              if(window.shareFixture.plans[0]?.shareId!=='ma-repo-000002'||window.shareFixture.plans[0]?.type!=='official')throw Error('Wrong official plan identity')
            }else{
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes('SHARE_IMPORT_FAILED')))
              if(button('Create installation plan')||window.shareFixture.plans.length)throw Error('Wrong collection allowed plan')
            }
            if(window.shareFixture.requests!==1||!window.shareFixture.lastRequest.url.endsWith('/official_share_import')||window.shareFixture.lastRequest.body.share_id!=='ma-repo-000002')throw Error('Wrong official request')
            return
          }
          if(mode.startsWith('en-')){
            if(/[\u4e00-\u9fff]/.test(document.body.innerText))throw Error('Chinese UI copy in English import')
            await fill(document.querySelector('input'),'SHARE-EN')
            button('Import and verify').click()
            await wait(()=>button('Create installation plan'))
            if(/[\u4e00-\u9fff]/.test(document.body.innerText))throw Error('Chinese UI copy in English preview')
            if(!document.body.innerText.includes('may still need verification'))throw Error('Preview overstates source verification')
            const plan=button('Create installation plan')
            if(mode.startsWith('en-version-')){
              const expected=mode==='en-version-different'?'Version differs — local 2; shared 1':mode==='en-version-matching'?'recorded version matches (1)':'version comparison unavailable'
              if(!document.body.innerText.includes(expected)||!document.body.innerText.includes('does not verify file contents'))throw Error('Version distinction missing')
              if(window.shareFixture.requests!==1||window.shareFixture.plans.length)throw Error('Version review auto-mutated')
              if(!document.body.innerText.includes(mode==='en-version-different'?'File state differs — local disabled files; shared active files':'File state comparison unavailable'))throw Error('File state difference or unknown missing')
            }
            if(mode==='en-prerequisite'||mode==='en-unknown'){
              if(mode==='en-unknown'&&(document.body.innerText.includes('future_')||!document.body.innerText.includes('Verification pending')))throw Error('Unknown status not localized conservatively')
              if(!plan.disabled)throw Error('Missing prerequisites permit main plan')
              button('Review prerequisites').click()
              if(window.shareFixture.plans[0]?.action!=='prerequisite_plan')throw Error('Wrong prerequisite action')
            }else if(mode==='en-empty'){
              if(!plan.disabled||!document.body.innerText.includes('collection is empty'))throw Error('Empty collection misleading')
              plan.click()
              if(window.shareFixture.plans.length)throw Error('Empty collection dispatched')
            }else{
              if(mode==='en-included'&&!document.body.innerText.includes('Included in collection'))throw Error('Included dependency mislabeled')
              if(plan.disabled)throw Error('Valid collection unexpectedly blocked')
              plan.click()
              if(window.shareFixture.plans[0]?.share!=='SHARE-EN')throw Error('English plan did not forward verified input')
            }
            return
          }
          if(mode.startsWith('export-')){
            await fill(document.querySelector('input'),'Fixture title')
            await fill(document.querySelector('textarea'),'Fixture description')
            button('导出投稿包').click()
            if(mode.startsWith('export-copy-')){
              await wait(()=>button('前往官方审核投稿页'))
              const target=[...document.querySelectorAll('button')].filter(b=>b.textContent==='复制')[mode==='export-copy-empty'?1:0]
              target.click();if(mode!=='export-copy-empty')target.click()
              const expected={'export-copy-valid':'标题已复制','export-copy-error':'COPY_FAILED','export-copy-timeout':'COPY_TIMEOUT','export-copy-empty':'COPY_EMPTY'}[mode]
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes(expected)))
              await wait(()=>!document.querySelector('[role=status]'))
              if((window.shareFixture.copies||0)!==(mode==='export-copy-empty'?0:1))throw Error('Duplicate or empty clipboard write')
              if(mode==='export-copy-timeout'){
                window.shareFixture.finishCopy();await new Promise(r=>setTimeout(r,30))
              }
              if(mode!=='export-copy-valid'&&window.shareFixture.toasts.some(t=>t.includes('标题已复制')))throw Error('False copy success')
              if(window.shareFixture.toasts.some(t=>t.includes('private clipboard')))throw Error('Private exception leaked')
              return
            }
            if(mode.startsWith('export-page-')){
              await wait(()=>button('前往官方审核投稿页'))
              await wait(()=>!button('前往官方审核投稿页').disabled)
              const target=button('前往官方审核投稿页');target.click();target.click()
              const expected=mode==='export-page-valid'?'打开页面不代表已投稿':'SHARE_PAGE_UNCONFIRMED'
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes(expected)))
              await wait(()=>!button('前往官方审核投稿页').disabled)
              if(window.shareFixture.opens!==1||window.shareFixture.downloads!==1)throw Error('Duplicate page open or file save')
              if(window.shareFixture.toasts.some(t=>t.includes('private native')))throw Error('Raw exception leaked')
              const records=JSON.parse(localStorage.getItem('modagent-p-share-submissions-v1'))
              if(records[0].status!==(mode==='export-page-valid'?'submission_opened':'draft'))throw Error('Wrong submission state')
              return
            }
            if(mode==='export-valid')await wait(()=>window.shareFixture.downloads===1)
            else if(mode==='export-saveerror'){
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes('SHARE_RECORD_FAILED')))
              if(window.shareFixture.downloads!==1||!button('前往官方审核投稿页')||!document.querySelector('[role=alert]'))throw Error('Saved file outcome lost on record failure')
              if(window.shareFixture.toasts.some(t=>t.includes('SHARE_EXPORT_FAILED')))throw Error('Saved export reported failed')
            }
            else if(mode==='export-cancel'){
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes('已取消保存')))
              if(window.shareFixture.downloads||button('前往官方审核投稿页'))throw Error('Cancelled save reported exported')
              if(document.querySelector('input').value!=='Fixture title')throw Error('Cancelled draft lost')
            }
            else{
              await wait(()=>window.shareFixture.toasts.some(t=>t.includes('SHARE_EXPORT_FAILED')))
              if(window.shareFixture.downloads)throw Error('Invalid export downloaded')
              if(document.querySelector('input').value!=='Fixture title')throw Error('Export draft lost')
            }
            return
          }
          const input=document.querySelector('input')
          await fill(input,'SHARE-A')
          button('导入并核验').click()
          if(mode==='valid'){
            await wait(()=>button('生成安装计划'))
            await fill(input,'SHARE-B')
            if(button('生成安装计划'))throw Error('Stale verification still actionable')
            button('导入并核验').click()
            await wait(()=>button('生成安装计划'))
            button('生成安装计划').click()
            if(window.shareFixture.plans[0]?.share!=='SHARE-B')throw Error('Wrong verified input forwarded')
          }else{
            if(mode==='import-body')input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
            await wait(()=>window.shareFixture.toasts.some(t=>t.includes('SHARE_IMPORT_FAILED')))
            if(button('生成安装计划'))throw Error('Invalid import exposed plan')
            if(input.value!=='SHARE-A'||window.shareFixture.requests!==1)throw Error('Lost input or duplicate request')
          }
        })()`)
        results.push({mode,passed:true})
      }catch(e){results.push({mode,passed:false,error:e.message})}
    }
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2))
    results.forEach(r=>console.log((r.passed?'PASS ':'FAIL ')+r.mode))
    win.destroy();app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
