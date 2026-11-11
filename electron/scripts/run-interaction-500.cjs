// Fixed two-round UI campaign. Mocked transport; no live games or paid models.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto')
const {spawnSync} = require('node:child_process')
const repo = path.resolve(__dirname, '../..')
const output = path.join(repo, 'build', 'interaction-500-' + new Date().toISOString().replace(/[:.]/g, '-') )
fs.mkdirSync(output, {recursive: false})
const suites = [
  ['mod-list',79], ['snapshot',43], ['settings-save',46], ['share',29],
  ['app-connection',23], ['setup',6], ['game-import-app',4],
  ['error-boundary',10], ['chat-scope',9], ['connection',1],
].map(([name,count]) => ({name,count,script:path.join(__dirname,`test-${name}-ui.cjs`)}))
const hash = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')
const hashes = {}
function record(directory) {
  for(const entry of fs.readdirSync(directory,{withFileTypes:true})) {
    const file=path.join(directory,entry.name)
    if(entry.isDirectory() && entry.name!=='__pycache__') record(file)
    else if(entry.isFile() && /\.(py|jsx?|mjs|cjs)$/.test(file)) hashes[path.relative(repo,file)]=hash(file)
  }
}
record(path.join(repo,'modagent'));record(path.join(repo,'electron/src'));record(path.join(__dirname,'fixtures'))
for(const s of suites) {
  hashes[path.relative(repo,s.script)]=hash(s.script)
  if(!['error-boundary','connection'].includes(s.name)) {
    const match=fs.readFileSync(s.script,'utf8').match(/for\s*\(const mode of (\[[^\]]+\])/)
    if(!match) throw Error('Cannot enumerate '+s.name)
    s.modes=JSON.parse(match[1].replace(/'/g,'"'))
  } else if(s.name==='error-boundary') {
    s.modes=['en','zh-CN'].flatMap(language=>['success','error','timeout','missing','initial'].map(mode=>language+':'+mode))
  } else s.modes=['connection-flow']
  if(s.modes.length!==s.count) throw Error('Count mismatch '+s.name)
}
if(suites.reduce((n,s)=>n+s.count,0)!==250) throw Error('Expected exactly 250 cases per round')
fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify({rounds:2,planned:500,suites,hashes,scope:'Real Electron/React components, synthetic transport. No real game writes or external-service/model validation.'},null,2))
const rows=[], runs=[]
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
function save() {
  const counts={passed:rows.filter(r=>r.status==='passed').length,failed:rows.filter(r=>r.status==='failed').length,unconfirmed:rows.filter(r=>r.status==='unconfirmed').length}
  const report={planned:500,recorded:rows.length,counts,runs,rows}
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2))
  fs.writeFileSync(path.join(output,'report.html'),`<!doctype html><meta charset="utf-8"><title>ModAgent 500 次交互检查</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:16px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:7px;text-align:left}.failed,.unconfirmed{background:#ffe4dc}.passed{color:#176235}</style><h1>ModAgent：500 次隔离界面检查</h1><p>250 个场景 × 2 轮；真实 Electron/React 组件，模拟后台响应。不是 500 个独立场景，不代表真实游戏、外站或模型全链通过。</p><p>已记录 ${rows.length}/500；通过 ${counts.passed}；失败 ${counts.failed}；未确认 ${counts.unconfirmed}。失败不自动重跑。</p><p>每轮启动独立进程和测试配置。快照界面检查不等于真实文件回滚；文件回滚另测。缺失结果不算通过。</p><table><tr><th>轮次</th><th>模块</th><th>场景</th><th>结果</th><th>错误</th></tr>${rows.map(r=>`<tr class="${r.status}"><td>${r.round}</td><td>${esc(r.suite)}</td><td>${esc(r.mode)}</td><td>${r.status}</td><td>${esc(r.error||'')}</td></tr>`).join('')}</table>`)
}
console.log('OUTPUT '+output)
for(let round=1;round<=2;round++) for(const suite of suites) {
  const dir=path.join(output,`round-${round}`,suite.name);fs.mkdirSync(dir,{recursive:true})
  // Build the existing conversation fixture without running additional cases.
  if(suite.name==='chat-scope') {
    require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures/conversation-ui.jsx')],bundle:true,outfile:path.join(dir,'app.js'),platform:'browser',format:'iife',alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},loader:{'.png':'dataurl','.mp3':'dataurl'},define:{'import.meta.env':'{}','process.env.NODE_ENV':'"test"'}})
    fs.writeFileSync(path.join(dir,'index.html'),'<html><meta charset="utf-8"><div id="root"></div><script src="app.js"></script></html>')
  }
  const start=Date.now()
  const result=spawnSync(process.execPath,[suite.script],{cwd:path.resolve(__dirname,'..'),env:{...process.env,MODAGENT_UI_TEST_OUTPUT:dir},encoding:'utf8',timeout:90000,windowsHide:true,maxBuffer:8*1024*1024})
  fs.writeFileSync(path.join(dir,'process.log'),(result.stdout||'')+'\n'+(result.stderr||'')+'\n'+(result.error?.message||''))
  const resultFile=path.join(dir,suite.name==='chat-scope'?'scope-result.json':'result.json')
  let data=[]
  try {data=JSON.parse(fs.readFileSync(resultFile,'utf8'));if(!Array.isArray(data))data=[{...data,mode:'connection-flow'}]}catch{}
  for(const mode of suite.modes) {
    const item=data.find(r=>(r.language?r.language+':'+r.mode:r.mode)===mode)
    const status=item?.passed===false?'failed':item?.passed===true&&result.status===0?'passed':'unconfirmed'
    rows.push({round,suite:suite.name,mode,status,error:item?.error||(status==='unconfirmed'?'Missing case result or unsuccessful process; inspect process.log':''),evidence:path.relative(output,resultFile)})
  }
  runs.push({round,suite:suite.name,exitCode:result.status,error:result.error?.message,elapsedMs:Date.now()-start,resultCount:data.length,expected:suite.count})
  save()
  console.log(JSON.stringify({round,suite:suite.name,...runs.at(-1),passed:rows.filter(r=>r.round===round&&r.suite===suite.name&&r.status==='passed').length}))
}
const changed=Object.entries(hashes).filter(([p,h])=>hash(path.join(repo,p))!==h).map(([p])=>p)
fs.writeFileSync(path.join(output,'source-integrity.json'),JSON.stringify({unchanged:changed.length===0,changed},null,2))
console.log('COMPLETE '+output)
process.exitCode=rows.length===500&&rows.every(r=>r.status==='passed')&&!changed.length?0:1
