const fs = require('node:fs')
const path = require('node:path')
const root = process.env.MODAGENT_UI_TEST_OUTPUT || path.resolve(__dirname, '../../build/connection-test-ui')
if (!process.versions.electron) {
  ;(async () => {
    fs.mkdirSync(root, { recursive: true })
    fs.writeFileSync(path.join(root, 'index.html'), '<html><meta charset="utf-8"><body class="bg-surface-900 text-white font-sans"><div id="root"></div><script type="module" src="/fixture.jsx"></script></body></html>')
    const { build } = require('vite')
    await build({configFile:false, root, logLevel:'warn', plugins:[{
      name:'fixture', resolveId(id) { if (id === '/fixture.jsx') return path.join(__dirname, 'fixtures/connection-test-ui.jsx') },
    }], css:{postcss:path.resolve(__dirname,'..')}, build:{outDir:path.join(root,'dist'),emptyOutDir:true},base:'./'})
    const r = require('node:child_process').spawnSync(require('electron'), [__filename], {encoding:'utf8',timeout:45000,windowsHide:true})
    process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '')
    if (r.error) throw r.error
    process.exit(r.status ?? 1)
  })().catch(e => {console.error(e);process.exit(1)})
} else {
  const {app,BrowserWindow,session} = require('electron')
  app.setPath('userData', path.join(root,'isolated-profile'))
  app.whenReady().then(async () => {
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']}, (_d, cb) => cb({cancel:true}))
    const win = new BrowserWindow({show:false,width:820,height:1140,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}})
    const errors=[]
    win.webContents.on('console-message',(_e,level,message)=>{if(level>=3)errors.push(message)})
    await win.loadFile(path.join(root,'dist/index.html'))
    const result = await win.webContents.executeJavaScript(`(async()=>{
      const wait=async(fn)=>{for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,30))}throw Error('UI timeout')}
      const cards=()=>[...document.querySelectorAll('[data-connection-target]')]
      const card=id=>document.querySelector('[data-connection-target="'+id+'"]')
      const findButton=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
      await wait(()=>cards().length===7)
      if(window.fixture.requests.length)throw Error('Unexpected automatic external request')
      findButton('测试全部').click()
      await wait(()=>findButton('测试中…'))
      if(!findButton('测试中…').disabled || cards().some(c=>!c.querySelector('button').disabled))throw Error('Duplicate probes not blocked')
      await wait(()=>window.fixture.requests.length===7 && window.fixture.active===0 && findButton('测试全部'))
      if(window.fixture.peak>3)throw Error('Too many concurrent probes')
      if(!card('nexus').textContent.includes('站点拒绝访问') || !card('nexus').textContent.includes('HTTP 403'))throw Error('403 classification')
      if(!card('modio').textContent.includes('连接超时'))throw Error('Timeout classification')
      if(!card('gamebanana').textContent.includes('收到重定向'))throw Error('Redirect classification')
      if(!card('workshop').textContent.includes('本地诊断服务失败'))throw Error('Local error mislabeled as site failure')
      return {requests:window.fixture.requests,peak:window.fixture.peak}
    })()`)
    await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    fs.writeFileSync(path.join(root,'connection-zh.png'),(await win.webContents.capturePage()).toPNG())
    await win.webContents.executeJavaScript(`(async()=>{
      document.querySelector('#language').click()
      await new Promise(r=>setTimeout(r,50))
      if(!document.body.textContent.includes('Access restricted'))throw Error('English status missing')
      window.fixture.retry=true
      document.querySelector('[data-connection-target="nexus"] button').click()
      for(let i=0;i<100;i++){
        await new Promise(r=>setTimeout(r,30))
        const card=document.querySelector('[data-connection-target="nexus"]')
        if(card.textContent.includes('Connected (HTTP)')){
          if(card.textContent.includes('HTTP 403'))throw Error('Stale status retained')
          if(window.fixture.requests.length!==8)throw Error('Retry affected other targets')
          return
        }
      }
      throw Error('Retry timeout')
    })()`)
    await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    fs.writeFileSync(path.join(root,'connection-en.png'),(await win.webContents.capturePage()).toPNG())
    if(errors.length)throw Error(errors.join('\n'))
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:true,...result},null,2))
    console.log('CONNECTION UI PASSED: bounded test-all, individual retry, truthful HTTP/local errors, Chinese/English; mocked network only')
    win.destroy(); app.exit(0)
  }).catch(e=>{console.error(e);app.exit(1)})
}
