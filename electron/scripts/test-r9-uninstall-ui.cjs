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
    for (const scenario of ['preview-failed', 'partial', 'success', 'batch', 'batch-snapshot-invalid', 'batch-body', 'batch-switch','workshop-preview','unsafe-preview','en-workshop-preview','en-unsafe-preview','en-batch','en-batch-snapshot-invalid','en-batch-body','en-batch-switch','en-partial','en-success',...['invalid-count','invalid-id','invalid-kind','invalid-dependencies'].flatMap(type=>['preview-'+type,'batch-'+type])]) {
      const mode=scenario.replace(/^en-/,'')
      await win.loadFile(path.join(root, 'index.html'), { query: { scenario:mode,language:scenario.startsWith('en-')?'en':'zh-CN' } })
      results.push(await win.webContents.executeJavaScript(`(async () => {
        const check = (condition, label) => { if (!condition) throw Error(label) }
        const wait = async predicate => { for (let i=0;i<80;i++) { if(predicate()) return; await new Promise(r=>setTimeout(r,50)) } throw Error('UI timeout') }
        const en=${scenario.startsWith('en-')}
        const rowSelector=en?'button[title="Uninstall"]':'button[title="删除"]'
        await wait(() => document.querySelector(rowSelector))
        window.fixture.scenario = ${JSON.stringify(mode)}
        const labels={'全选':'Select all','批量删除':'Uninstall selected','确认全部卸载':'Confirm uninstall selected','删除':'Uninstall'}
        const button = text => [...document.querySelectorAll('button')].find(b=>b.textContent.trim()===(en?labels[text]||text:text))
        if(window.fixture.scenario.includes('invalid-')){
          const batch=window.fixture.scenario.startsWith('batch-')
          if(batch){button('全选').click();await wait(()=>button('批量删除'));button('批量删除').click()}
          else document.querySelector(rowSelector).click()
          await wait(()=>window.fixture.toasts.some(t=>t.message.includes(batch?'BATCH_UNINSTALL_PREVIEW_FAILED':'MOD_UNINSTALL_PREVIEW_FAILED')))
          check(!button('确认全部卸载')&&!button('删除'),'Malformed preview exposed destructive confirmation')
          check(!window.fixture.calls.some(c=>c.args.confirmed||c.url.endsWith('/snapshot_create')),'Malformed preview started write')
          check(window.fixture.calls.filter(c=>c.url.endsWith('/mod_uninstall')).length===(batch?2:1),'Batch did not test a valid first item followed by malformed second item')
          return {scenario:window.fixture.scenario,passed:true}
        }
        if (window.fixture.scenario.startsWith('batch')) {
          button('全选').click()
          await wait(()=>button('批量删除'))
          button('批量删除').click()
          await wait(()=>button('确认全部卸载'))
          if(en)check(!/[\\u4e00-\\u9fff]/.test(document.querySelector('[role="dialog"]').textContent),'Chinese batch confirmation in English')
          button('确认全部卸载').click()
          if(window.fixture.scenario==='batch-switch'){
            await wait(()=>window.fixture.resolve)
            window.fixture.switchGame()
            await wait(()=>document.querySelector('[data-game="newfixture"]'))
            window.fixture.resolve()
            await wait(()=>window.fixture.toasts.some(t=>t.message.includes(en?'2 not started after switching games':'2 个因切换游戏未执行')))
            check(!window.fixture.calls.some(c=>c.args.confirmed),'Old-game snapshot triggered deletion')
            return {scenario:'batch-switch',passed:true}
          }
          if(window.fixture.scenario!=='batch'){
            const snapshot=window.fixture.scenario==='batch-snapshot-invalid'
            await wait(()=>window.fixture.toasts.some(t=>t.message.includes(snapshot?'BATCH_UNINSTALL_SNAPSHOT_UNCONFIRMED':'BATCH_UNINSTALL_UNCONFIRMED')))
            check(window.fixture.calls.filter(c=>c.url.endsWith('/mod_uninstall')&&c.args.confirmed).length===(snapshot?0:1),'Failure continued deleting')
            check(!window.fixture.feedback.some(f=>f.type==='remove-complete'),'Unconfirmed deletion emitted success')
            check(document.body.textContent.includes('Failed Mod'),'Unprocessed item lost')
            return {scenario:window.fixture.scenario,passed:true}
          }
          await wait(()=>window.fixture.toasts.some(t=>t.message.includes(en?'Uninstalled 1; 1 failed or unconfirmed':'已卸载 1 个；1 个失败或未确认')))
          check(window.fixture.toasts.some(t=>t.message.includes(en?'Uninstall is not fully confirmed':'卸载未全部确认完成')),'Batch hid partial outcome details')
          check(window.fixture.feedback.filter(f=>f.type==='remove-complete').length===1, 'batch success count incorrect')
          check(window.fixture.feedback.find(f=>f.type==='remove-complete').count===1, 'partial counted as success')
          check(document.body.textContent.includes('Failed Mod'), 'failed target removed')
          return { scenario: 'batch', passed: true, toasts: window.fixture.toasts }
        }
        document.querySelector(rowSelector).click()
        if(window.fixture.scenario.endsWith('-preview')){
          await wait(()=>document.querySelector('[role="dialog"]'))
          const text=document.querySelector('[role="dialog"]').textContent
          if(window.fixture.scenario==='workshop-preview'){
            check(text.includes(en?'cannot restore Steam subscriptions':'不能恢复 Steam 订阅'),'Unsubscription rollback boundary missing')
            check(!text.includes('此操作可回滚'),'Unsubscription falsely promised reversible')
          }else{
            check(text.includes(en?'1 paths were blocked':'1 条路径被安全检查拦下'),'Blocked paths hidden')
            check(text.includes('Dependent Mod'),'Dependency impact hidden')
          }
          if(en)check(!/[\\u4e00-\\u9fff]/.test(text),'Chinese uninstall dialog in English mode')
          button(en?'Cancel':'取消').click()
          check(!window.fixture.calls.some(c=>c.args.confirmed),'Preview or cancel performed uninstall')
          return {scenario:${JSON.stringify(scenario)},passed:true}
        }
        const confirm = () => button('删除')
        if (window.fixture.scenario === 'preview-failed') {
          await wait(() => window.fixture.toasts.length > 0)
          check(!confirm(), 'failed preview exposed confirmation')
          check(!window.fixture.calls.some(c=>c.args.confirmed), 'failed preview triggered uninstall')
        } else {
          await wait(confirm)
          confirm().click()
          await wait(() => window.fixture.toasts.some(t=>en?/uninstalled|not fully confirmed/.test(t.message):/已卸载|未全部确认/.test(t.message)))
          const feedback = window.fixture.feedback.filter(f=>f.type==='remove-complete')
          if (window.fixture.scenario === 'partial') {
            check(feedback.length===0, 'partial incorrectly emitted success')
            check(window.fixture.toasts.some(t=>t.message.includes(en?'not fully confirmed':'未全部确认')), 'missing partial explanation')
            check(document.body.textContent.includes('Fixture Mod'), 'partial record disappeared')
          } else {
            check(feedback.length===1, 'success feedback missing or duplicated')
            await wait(()=>!document.querySelector(rowSelector))
          }
        }
        return { scenario: window.fixture.scenario, passed: true, toasts: window.fixture.toasts }
      })()`))
    }
    if (errors.length) throw Error(errors.join('\n'))
    fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify({ passed: true, results, rendererErrors: errors }, null, 2))
    console.log(results.length+' real uninstall UI scenarios passed')
    win.destroy()
    app.exit(0)
  }).catch(error => { console.error(error); app.exit(1) })
}
