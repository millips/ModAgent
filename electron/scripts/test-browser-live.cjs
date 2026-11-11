const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const {createBrowserController,readCdp,cdpCall}=require('../browserController');
const {installedBrowsers}=require('../browserLauncher');
const output=path.resolve(__dirname,'../../build/browser-r29-verification');
fs.mkdirSync(output,{recursive:true});
const root=fs.mkdtempSync(path.join(os.tmpdir(),'modagent-browser-r29-'));
async function port(){const s=http.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function bounds(p){const v=await readCdp(p,'/json/version');const {targetInfos}=await cdpCall(v.webSocketDebuggerUrl,'Target.getTargets');const target=targetInfos.find(t=>t.type==='page');const w=await cdpCall(v.webSocketDebuggerUrl,'Browser.getWindowForTarget',{targetId:target.targetId});return {endpoint:v.webSocketDebuggerUrl,state:w.bounds.windowState};}
(async()=>{
  const browsers=installedBrowsers(),reports=[];
  for(const browser of browsers) {
    const dataDir=path.join(root,browser.id),p=await port();
    const observations=[];
    const options={dataDir,port:p,discover:()=>[browser],warmupSites:[],
      read:async(port,route)=>{const r=await readCdp(port,route);observations.push({route,result:r});return r;},
      command:async(...args)=>{try{return await cdpCall(...args)}catch(e){observations.push({command:args[1],error:e.message,cause:e.cause});throw e;}}};
    let c=createBrowserController(options);
    try {
      const initial=await c.start();
      if(initial.phase!=='ready'){
        fs.writeFileSync(path.join(output,'failed-live-diagnostic.json'),JSON.stringify({initial,observations:observations.slice(-8)},null,2));
        console.error(JSON.stringify({initial,diagnostic:'failed-live-diagnostic.json'}));
      }
      assert.equal(initial.phase,'ready');
      assert.equal((await bounds(p)).state,'minimized');
      assert((await c.show()).ok);assert.equal((await bounds(p)).state,'normal');
      assert((await c.minimize()).ok);assert.equal((await bounds(p)).state,'minimized');
      const endpoint=(await bounds(p)).endpoint;
      await cdpCall(endpoint,'Storage.setCookies',{cookies:[{name:'modagent_fixture_only',value:'retained',url:'http://127.0.0.1/',expires:Math.floor(Date.now()/1000)+3600}]});
      await c.stop();
      c=createBrowserController(options);
      assert.equal((await c.start()).phase,'ready');
      const nextEndpoint=(await bounds(p)).endpoint;
      const {cookies}=await cdpCall(nextEndpoint,'Storage.getCookies');
      assert(cookies.some(x=>x.name==='modagent_fixture_only'&&x.value==='retained'));
      assert.equal((await bounds(p)).state,'minimized');
      reports.push({browser:browser.id,passed:true,minimized:true,restore:true,minimizeAgain:true,persistentSyntheticCookie:true});
      console.log('PASS actual '+browser.name+' minimize/restore/restart cookie');
    } finally {await c.stop();}
  }
  if(browsers.some(b=>b.id==='chrome')&&browsers.some(b=>b.id==='edge')) {
    const c=createBrowserController({dataDir:path.join(root,'fallback'),port:await port(),warmupSites:[],discover:()=>browsers.filter(b=>['chrome','edge'].includes(b.id)),
      launch:(exe,args,options)=>spawn(exe.toLowerCase().endsWith('chrome.exe')?path.join(root,'intentionally-missing-chrome.exe'):exe,args,options)});
    try {const s=await c.start();assert.equal(s.phase,'ready');assert.equal(s.id,'edge');assert.equal(s.attempts[0].reason,'launch_failed');
      reports.push({scenario:'chrome-spawn-failure-to-real-edge',passed:true});console.log('PASS injected Chrome startup failure -> actual Edge');
    } finally{await c.stop();}
  }
  fs.writeFileSync(path.join(output,'live-result.json'),JSON.stringify({fixture:root,realUserProfilesTouched:false,reports},null,2));
})().catch(e=>{console.error(e);console.error('Fixture retained: '+root);process.exitCode=1});
