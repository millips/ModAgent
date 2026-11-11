const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createBrowserController,localEndpoint}=require('../browserController');
const {installedBrowsers,browserCandidates}=require('../browserLauncher');
const path=require('node:path');
const candidates=[{id:'chrome',name:'Chrome',executable:'C:/chrome.exe'},{id:'edge',name:'Edge',executable:'C:/msedge.exe'}];
const endpoint='ws://127.0.0.1:12345/devtools/browser/fixture';

function fixture(mode) {
  const calls=[], launches=[], saved=[];
  let marker='',current='',closed=false, minimized=false;
  const control=createBrowserController({dataDir:'C:/fixture-only',port:12345,startTimeout:230,
    loadPreference:()=>({}),savePreference:p=>saved.push(p),
    discover:()=>mode==='missing'?[]:candidates,
    launch:(exe,args)=>{
      launches.push({exe,args});current=exe;marker=args.at(-1);closed=false;
      const child=new EventEmitter();child.unref=()=>{};child.exitCode=0;child.kill=()=>{closed=true};
      if(mode==='spawn-fail' && exe.includes('chrome'))process.nextTick(()=>child.emit('error',Error()));
      return child;
    },
    read:async(_port,route)=>{
      if(mode==='occupied')return {webSocketDebuggerUrl:'ws://127.0.0.1:12345/devtools/browser/stranger'};
      if(!current || closed || (['spawn-fail','health-fail'].includes(mode) && current.includes('chrome')))throw Error();
      return route==='/json/version'?{webSocketDebuggerUrl:endpoint}:[{type:'page',url:mode==='wrong-owner'?'about:blank':marker}];
    },
    command:async(_endpoint,method,args)=>{
      calls.push({method,args});
      if(method==='Target.getTargets')return {targetInfos:[{type:'page',targetId:'p1',url:'about:blank'}]};
      if(method==='Browser.getWindowForTarget')return {windowId:1};
      if(method==='Browser.setWindowBounds')minimized=args.bounds.windowState==='minimized';
      if(method==='Browser.close')closed=true;
      if(method==='Target.createTarget')return {targetId:'created'};
      return {};
    }});
  return {control,calls,launches,saved,get minimized(){return minimized}};
}

(async()=>{
  for(const mode of ['ok','spawn-fail','health-fail','missing','occupied','wrong-owner']) {
    const f=fixture(mode),s=await f.control.start();
    if(['missing','occupied','wrong-owner'].includes(mode)) {
      assert.equal(s.phase,mode==='missing'?'missing':'failed');assert.equal(f.saved.length,0);
      assert(!f.calls.some(c=>c.method==='Browser.close'),'unowned browser must not be closed');
    } else {
      assert.equal(s.phase,'ready');assert(f.minimized);
      assert.equal(f.saved[0].id,mode==='ok'?'chrome':'edge');
      assert(f.launches.every(l=>l.args.includes('--start-minimized') && !l.args.some(a=>a.startsWith('https:'))));
      assert((await f.control.show()).ok);assert(!f.minimized);
      assert((await f.control.minimize()).ok);assert(f.minimized);
      const before=f.calls.length;
      await f.control.show({automatic:true,key:'gate-1'});
      const after=f.calls.length;assert(after>before);
      assert((await f.control.show({automatic:true,key:'gate-1'})).suppressed);
      assert.equal(f.calls.length,after);
      await f.control.show({site:'file:///private'});
      assert(!f.calls.some(c=>c.method==='Target.createTarget' && c.args.url.startsWith('file:')));
    }
    await f.control.stop();console.log('PASS '+mode);
  }
  const env={ProgramFiles:'C:/Programs',LOCALAPPDATA:'C:/Local'};
  const all=browserCandidates(env);
  const edge=all.find(b=>b.id==='edge').paths[0];
  const remembered=installedBrowsers(env,'',()=>true,{id:'edge',executable:edge});
  assert.equal(remembered[0].id,'edge');
  const portable=path.resolve('D:/Portable/chrome.exe');
  assert.equal(installedBrowsers(env,'',p=>p===portable,{id:'chrome',executable:portable})[0].executable,portable);
  for(const u of ['wss://127.0.0.1:12345/devtools/browser/a','ws://evil.test:12345/devtools/browser/a','ws://127.0.0.1:9999/devtools/browser/a','ws://user@127.0.0.1:12345/devtools/browser/a'])assert(!localEndpoint(u,12345));
  assert(localEndpoint(endpoint,12345));
  console.log('PASS remembered browser, portable location and endpoint ownership');
})().catch(e=>{console.error(e);process.exitCode=1});
