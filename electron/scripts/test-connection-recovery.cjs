// Run after test-connection-ui.cjs builds the fixture. No real network allowed.
const fs = require('node:fs')
const path = require('node:path')
const root = path.resolve(__dirname, '../../build/connection-test-ui')
if (!process.versions.electron) {
  const r = require('node:child_process').spawnSync(require('electron'), [__filename], {
    encoding: 'utf8', timeout: 60000, windowsHide: true,
  })
  process.stdout.write(r.stdout || ''); process.stderr.write(r.stderr || '')
  if (r.error) throw r.error
  process.exit(r.status ?? 1)
} else {
  const {app, BrowserWindow, session} = require('electron')
  app.setPath('userData', path.join(root, 'recovery-profile'))
  app.whenReady().then(async () => {
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']}, (_d, cb) => cb({cancel:true}))
    const win = new BrowserWindow({show:false, webPreferences:{sandbox:true, contextIsolation:true, nodeIntegration:false, backgroundThrottling:false}})
    const results = []
    for (const scenario of ['bad-url', 'duplicate-id', 'http-failure', 'bad-result', 'stalled-body', 'stalled-list', 'unmount-body']) {
      await win.loadFile(path.join(root, 'dist/index.html'), {query: {scenario}})
      try {
        await win.webContents.executeJavaScript(`(async () => {
          const scenario = ${JSON.stringify(scenario)}
          const wait = async (fn, ms=2000) => {
            const end = performance.now()+ms
            while(performance.now()<end) {
              if(fn()) return
              await new Promise(r=>setTimeout(r,25))
            }
            throw Error('Recovery condition not reached: '+scenario)
          }
          const cards=()=>document.querySelectorAll('[data-connection-target]')
          const alert=()=>document.querySelector('[role=alert]')
          if(['bad-url','duplicate-id','http-failure','stalled-list'].includes(scenario)) {
            await wait(alert, scenario==='stalled-list'?14000:2000)
            if(cards().length) throw Error('Invalid targets rendered')
            window.fixture.retry=true
            alert().querySelector('button').click()
            await wait(()=>cards().length===7 && !alert())
            if(window.fixture.requests.length) throw Error('Retry triggered external probes')
          } else {
            await wait(()=>cards().length===7)
            const card=()=>cards()[0]
            card().querySelector('button').click()
            await wait(()=>window.fixture.requests.length===1)
            if(scenario==='unmount-body') {
              document.querySelector('#toggle').click()
              await wait(()=>window.fixture.aborts===1)
            } else {
              await wait(()=>card().textContent.includes('本地诊断服务失败'), scenario==='stalled-body'?14000:2000)
              if(card().querySelector('button').disabled) throw Error('Retry stayed disabled')
              if(scenario==='stalled-body' && window.fixture.aborts!==1) throw Error('Body not aborted')
            }
          }
        })()`)
        results.push({scenario, passed:true})
      } catch(e) {
        results.push({scenario, passed:false, error:e.message})
      }
    }
    fs.writeFileSync(path.join(root, 'recovery-result.json'), JSON.stringify(results,null,2))
    for(const r of results) console.log((r.passed?'PASS ':'FAIL ')+r.scenario)
    win.destroy(); app.exit(results.every(r=>r.passed)?0:1)
  }).catch(e=>{console.error(e);app.exit(1)})
}
