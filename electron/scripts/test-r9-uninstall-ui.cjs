// Actual React buttons in an isolated, hidden Electron window; transport mocked.
const fs = require('node:fs')
const path = require('node:path')
const root = path.resolve(__dirname, '../../build/reliability-r9/uninstall-ui')
if (!process.versions.electron) {
  const { buildSync } = require('esbuild')
  const { spawnSync } = require('node:child_process')
  fs.mkdirSync(root, { recursive: true })
  buildSync({ entryPoints: [path.join(__dirname, 'fixtures/r9-uninstall-ui.jsx')], bundle: true,
    outfile: path.join(root, 'app.js'), platform: 'browser', format: 'iife',
    define: { __MODAGENT_SUBSCRIPTION__: 'false', 'import.meta.env': '{}', 'process.env.NODE_ENV': '"test"' },
  })
  fs.writeFileSync(path.join(root, 'index.html'), '<meta charset="utf-8"><div id="root"></div><script src="app.js"></script>')
  const result = spawnSync(require('electron'), [__filename], { encoding: 'utf8', timeout: 45000, windowsHide: true })
  process.stdout.write(result.stdout || '')
  process.stderr.write(result.stderr || '')
  if (result.error) throw result.error
  process.exit(result.status ?? 1)
} else {
  const { app, BrowserWindow, session } = require('electron')
  app.setPath('userData', path.join(root, 'isolated-profile'))
  app.whenReady().then(async () => {
    session.defaultSession.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*'] }, (_d, cb) => cb({ cancel: true }))
    const win = new BrowserWindow({ show: false, width: 1300, height: 900,
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } })
    const errors = []
    win.webContents.on('console-message', (_e, level, message) => { if (level >= 3) errors.push(message) })
    const results = []
    for (const scenario of ['preview-failed', 'partial', 'success', 'batch']) {
      await win.loadFile(path.join(root, 'index.html'), { query: { scenario } })
      results.push(await win.webContents.executeJavaScript(`(async () => {
        const check = (condition, label) => { if (!condition) throw Error(label) }
        const wait = async predicate => { for (let i=0;i<80;i++) { if(predicate()) return; await new Promise(r=>setTimeout(r,50)) } throw Error('UI timeout') }
        await wait(() => document.querySelector('button[title="删除"]'))
        window.fixture.scenario = ${JSON.stringify(scenario)}
        const button = text => [...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
        if (window.fixture.scenario === 'batch') {
          button('全选').click()
          await wait(()=>button('批量删除'))
          button('批量删除').click()
          await wait(()=>button('确认全部卸载'))
          button('确认全部卸载').click()
          await wait(()=>window.fixture.toasts.some(t=>t.message.includes('已卸载 1 个；1 个失败')))
          check(window.fixture.feedback.filter(f=>f.type==='remove-complete').length===1, 'batch success count incorrect')
          check(window.fixture.feedback.find(f=>f.type==='remove-complete').count===1, 'partial counted as success')
          check(document.body.textContent.includes('Failed Mod'), 'failed target removed')
          return { scenario: 'batch', passed: true, toasts: window.fixture.toasts }
        }
        document.querySelector('button[title="删除"]').click()
        const confirm = () => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '删除')
        if (window.fixture.scenario === 'preview-failed') {
          await wait(() => window.fixture.toasts.length > 0)
          check(!confirm(), 'failed preview exposed confirmation')
          check(!window.fixture.calls.some(c=>c.args.confirmed), 'failed preview triggered uninstall')
        } else {
          await wait(confirm)
          confirm().click()
          await wait(() => window.fixture.toasts.some(t=>t.message.includes('已卸载')||t.message.includes('未全部确认')))
          const feedback = window.fixture.feedback.filter(f=>f.type==='remove-complete')
          if (window.fixture.scenario === 'partial') {
            check(feedback.length===0, 'partial incorrectly emitted success')
            check(window.fixture.toasts.some(t=>t.message.includes('未全部确认')), 'missing partial explanation')
            check(document.body.textContent.includes('Fixture Mod'), 'partial record disappeared')
          } else {
            check(feedback.length===1, 'success feedback missing or duplicated')
            await wait(()=>!document.querySelector('button[title="删除"]'))
          }
        }
        return { scenario: window.fixture.scenario, passed: true, toasts: window.fixture.toasts }
      })()`))
    }
    if (errors.length) throw Error(errors.join('\n'))
    fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify({ passed: true, results, rendererErrors: errors }, null, 2))
    console.log('4 real uninstall UI scenarios passed')
    win.destroy()
    app.exit(0)
  }).catch(error => { console.error(error); app.exit(1) })
}
