const http = require('node:http');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const WebSocket = require('ws');
const {installedBrowsers, profileDirectory, readBrowserPreference, saveBrowserPreference} = require('./browserLauncher');

const LOGIN_SITES = Object.freeze({nexus:'https://www.nexusmods.com/', steam:'https://steamcommunity.com/'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function readCdp(port, route, timeout=1000) {
  return new Promise((resolve, reject) => {
    const req = http.get({hostname:'127.0.0.1', port, path:route, agent:false}, res => {
      let body='';
      res.on('data', chunk => {body+=chunk; if(body.length>2000000)req.destroy(new Error('browser_response_limit'));});
      res.on('error', reject);
      res.on('end', () => {
        try { if(res.statusCode!==200)throw Error('browser_http_failed'); resolve(JSON.parse(body)); }
        catch { reject(new Error('browser_response_invalid')); }
      });
    });
    req.setTimeout(timeout, () => req.destroy(new Error('browser_timeout')));
    req.on('error', reject);
  });
}

function localEndpoint(value, port) {
  try {
    const u=new URL(value);
    return u.protocol==='ws:' && ['127.0.0.1','localhost'].includes(u.hostname)
      && Number(u.port)===port && /^\/devtools\/browser\/[a-zA-Z0-9-]+$/.test(u.pathname)
      && !u.username && !u.password && !u.search && !u.hash;
  } catch { return false; }
}

function cdpCall(endpoint, method, params={}, timeout=3000) {
  return new Promise((resolve, reject) => {
    const ws=new WebSocket(endpoint, {handshakeTimeout:timeout, maxPayload:2000000});
    let done=false;
    const finish=(error, value) => {
      if(done)return; done=true; clearTimeout(timer); ws.terminate();
      error ? reject(error) : resolve(value);
    };
    const timer=setTimeout(()=>finish(new Error('browser_command_timeout')),timeout);
    ws.on('error',()=>finish(new Error('browser_connection_failed')));
    ws.on('close',()=>finish(new Error('browser_connection_closed')));
    ws.on('open',()=>ws.send(JSON.stringify({id:1,method,params})));
    ws.on('message',data=>{
      try { const r=JSON.parse(data); if(r.id===1)finish(r.error?new Error('browser_command_failed',{cause:r.error}):null,r.result||{}); }
      catch { finish(new Error('browser_command_invalid')); }
    });
  });
}

function createBrowserController({dataDir, port, env=process.env, launch=spawn,
  discover=installedBrowsers, read=readCdp, command=cdpCall, startTimeout=10000,
  warmupSites=['steam'],
  loadPreference=()=>readBrowserPreference(dataDir), savePreference=value=>saveBrowserPreference(dataDir,value)}={}) {
  let state={phase:'idle',name:'',id:'',minimized:false,attempts:[]};
  let child=null, endpoint='', starting=null, stopped=false, selected=null, lastProbe=0;
  let queue=Promise.resolve(), lastAutomatic=0;
  const seenAutomatic=new Set();
  const snapshot=()=>({...state,attempts:[...state.attempts]});
  const owned=async()=>Boolean(endpoint && (await read(port,'/json/version')).webSocketDebuggerUrl===endpoint);
  const call=(method,params)=>command(endpoint,method,params);
  const pages=async()=>{
    const {targetInfos=[]}=await call('Target.getTargets');
    return targetInfos.filter(t=>t.type==='page');
  };
  async function prepareTabs() {
    // The existing Workshop adapter fetches within a Steam Community tab.
    // Keep that origin available in the background, without forcing a login.
    const tabs=await pages();
    for(const site of warmupSites) {
      if(LOGIN_SITES[site] && !tabs.some(t=>{try{return new URL(t.url).hostname===new URL(LOGIN_SITES[site]).hostname}catch{return false}})) {
        await call('Target.createTarget',{url:LOGIN_SITES[site],background:true});
      }
    }
  }
  async function setWindows(minimized, targetId) {
    const targets=targetId ? [{targetId}] : await pages();
    const windows=new Set();
    for(const target of targets) {
      const {windowId}=await call('Browser.getWindowForTarget',{targetId:target.targetId});
      if(windows.has(windowId))continue;
      windows.add(windowId);
      await call('Browser.setWindowBounds',{windowId,bounds:{windowState:minimized?'minimized':'normal'}});
    }
    if(!windows.size)throw Error('browser_no_window');
    if(!minimized && targetId)await call('Target.activateTarget',{targetId});
    state.minimized=minimized;
  }
  async function closeOwned() {
    try { if(await owned())await call('Browser.close'); } catch {}
    // Only the process handle created by this controller may be terminated.
    // Never kill browsers by executable name or by a debugging port.
    if(child && child.exitCode===null && child.signalCode===null) {
      for(let i=0;i<50 && child.exitCode===null;i++)await sleep(100);
      if(child.exitCode===null)try{child.kill();}catch{}
    }
    child=null;endpoint='';
  }
  async function begin(preference) {
    const attempts=[];
    state={phase:'starting',name:'',id:'',minimized:false,attempts};
    const candidates=discover(env,dataDir,undefined,preference);
    if(!candidates.length){state.phase='missing';return snapshot();}
    // Reuse only a connection identity persisted after our own verified launch.
    let existing;
    try {existing=await read(port,'/json/version');}catch{}
    if(existing) {
      selected=candidates.find(b=>b.id===preference.id && b.executable===preference.executable);
      if(selected && localEndpoint(preference.endpoint,port) && existing.webSocketDebuggerUrl===preference.endpoint) {
        endpoint=preference.endpoint;
        try {await prepareTabs();await setWindows(true);state={...state,phase:'ready',id:selected.id,name:selected.name};return snapshot();}
        catch {endpoint='';}
      }
      state.phase='failed';state.error='browser_port_busy';return snapshot();
    }
    for(const browser of candidates) {
      if(stopped)break;
      selected=browser;
      state.id=browser.id;state.name=browser.name;
      const marker='about:blank#modagent-'+crypto.randomUUID();
      let failed=false;
      try {
        child=launch(browser.executable,[
          `--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1',
          `--user-data-dir=${profileDirectory(dataDir,browser.id)}`,
          '--start-minimized','--window-size=1000,720','--no-first-run','--no-default-browser-check',
          '--disable-background-timer-throttling','--disable-renderer-backgrounding',
          '--disable-backgrounding-occluded-windows',marker,
        ],{stdio:'ignore',detached:true,windowsHide:true});
        child.once('error',()=>{failed=true;});
        child.unref();
        const deadline=Date.now()+startTimeout;
        while(!stopped && !failed && Date.now()<deadline) {
          try {
            const version=await read(port,'/json/version');
            const targets=await read(port,'/json/list');
            let verified=Array.isArray(targets) && targets.some(t=>t.type==='page' && t.url===marker);
            // Policies/extensions may replace the initial blank tab. Confirm the
            // OS process identity before controlling such a browser instead.
            if(!verified && localEndpoint(version.webSocketDebuggerUrl,port) && Number.isInteger(child.pid)) {
              const info=await command(version.webSocketDebuggerUrl,'SystemInfo.getProcessInfo');
              verified=Array.isArray(info.processInfo) && info.processInfo.some(p=>p.type==='browser' && Number(p.id)===child.pid);
            }
            if(localEndpoint(version.webSocketDebuggerUrl,port) && verified) {
              endpoint=version.webSocketDebuggerUrl;
              await prepareTabs();
              await setWindows(true);
              if(stopped)break;
              state={...state,phase:'ready',error:'',fallback:attempts.length>0,
                changedBrowser:Boolean(preference.id && preference.id!==browser.id)};
              try {savePreference({id:browser.id,executable:browser.executable,endpoint});}
              catch {state.preferenceNotSaved=true;}
              return snapshot();
            }
          } catch {}
          if(child.exitCode!==null && child.exitCode!==undefined)break;
          await sleep(150);
        }
      } catch {failed=true;}
      attempts.push({id:browser.id,reason:failed?'launch_failed':'connection_failed'});
      await closeOwned();
    }
    state.phase=stopped?'stopped':'failed';state.error='browser_start_failed';
    return snapshot();
  }
  function start(preference=loadPreference()) {
    if(stopped)return Promise.resolve(snapshot());
    if(starting)return starting;
    starting=begin(preference).finally(()=>{starting=null;});
    return starting;
  }
  async function status() {
    if(state.phase==='ready' && Date.now()-lastProbe>2000) {
      lastProbe=Date.now();
      try {if(!await owned())throw Error();}catch {state.phase='closed';}
    }
    return snapshot();
  }
  function serial(work) {const next=queue.then(work,work);queue=next.catch(()=>{});return next;}
  function show({site,automatic=false,key=''}={}) {
    return serial(async()=>{
      if(stopped)return {ok:false,error:'browser_stopped'};
      if(automatic) {
        if(seenAutomatic.has(key) || Date.now()-lastAutomatic<15000)return {ok:true,suppressed:true};
        seenAutomatic.add(key);if(seenAutomatic.size>100)seenAutomatic.delete(seenAutomatic.values().next().value);
        lastAutomatic=Date.now();
      }
      await status();
      if(state.phase!=='ready') {
        if(automatic)return {ok:false,error:'browser_unavailable'};
        await start();
      }
      if(state.phase!=='ready')return {ok:false,error:state.error||'browser_missing'};
      try {
        if(!await owned())throw Error();
        const tabs=await pages();
        const target=tabs.find(t=>{
          try {const h=new URL(t.url).hostname;return site==='nexus' ? /(^|\.)nexusmods\.com$/.test(h) : site==='steam' && /(^|\.)steamcommunity\.com$/.test(h);}catch{return false;}
        });
        let targetId=target?.targetId;
        if(!targetId && site && LOGIN_SITES[site])targetId=(await call('Target.createTarget',{url:LOGIN_SITES[site],background:true})).targetId;
        targetId ||= tabs.find(t=>!t.url.startsWith('about:blank'))?.targetId || tabs[0]?.targetId;
        if(!targetId)targetId=(await call('Target.createTarget',{url:'about:blank'})).targetId;
        await setWindows(false,targetId);
        return {ok:true};
      } catch {return {ok:false,error:'browser_show_failed'};}
    });
  }
  function minimize() {return serial(async()=>{
    try {if(!await owned())throw Error();await setWindows(true);return {ok:true};}
    catch{return {ok:false,error:'browser_minimize_failed'};}
  });}
  async function stop() {
    stopped=true;
    if(starting)await starting.catch(()=>{});
    await queue.catch(()=>{});
    await closeOwned();state.phase='stopped';
  }
  return {start,status,show,minimize,stop};
}

module.exports={createBrowserController,readCdp,cdpCall,localEndpoint};
