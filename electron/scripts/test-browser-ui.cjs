const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../../build/browser-r29-verification/ui');
if(!process.versions.electron){
 fs.mkdirSync(root,{recursive:true});
 const assets=path.resolve(__dirname,'../dist/assets');
 fs.copyFileSync(path.join(assets,fs.readdirSync(assets).find(n=>n.endsWith('.css'))),path.join(root,'style.css'));
 for(const [name,entry] of [['controls','browser-controls-ui'],['chat','conversation-ui']]){
  require('esbuild').buildSync({entryPoints:[path.join(__dirname,'fixtures',entry+'.jsx')],bundle:true,outfile:path.join(root,name+'.js'),platform:'browser',format:'iife',alias:{'@edition':path.resolve(__dirname,'../src/edition/free.jsx')},loader:{'.png':'dataurl','.mp3':'dataurl'},define:{'import.meta.env':'{}','process.env.NODE_ENV':'"test"'}});
  fs.writeFileSync(path.join(root,name+'.html'),`<html><meta charset="utf-8"><link rel="stylesheet" href="style.css"><body data-ma-theme="core"><div id="root"></div><script src="${name}.js"></script></body></html>`);
 }
 const r=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:45000,windowsHide:true});
 process.stdout.write(r.stdout||'');process.stderr.write(r.stderr||'');if(r.error)throw r.error;process.exit(r.status??1);
}else{
 const {app,BrowserWindow,session}=require('electron');app.setPath('userData',path.join(root,'profile'));
 app.whenReady().then(async()=>{
  session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_d,cb)=>cb({cancel:true}));
  const w=new BrowserWindow({show:false,width:1000,height:720,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}}),results=[];
  for(const language of ['zh-CN','en'])for(const mode of ['ready','missing','failure','verification','fallback']){
   await w.loadFile(path.join(root,'controls.html'),{query:{language,mode}});
   try{
    await w.webContents.executeJavaScript(`(async()=>{
     const mode=${JSON.stringify(mode)},en=${language==='en'},f=window.fixture;
     const wait=async pred=>{for(let i=0;i<100;i++){if(pred())return;await new Promise(r=>setTimeout(r,20))}throw Error('Browser UI timeout '+mode)};
     await wait(()=>document.querySelector('[data-browser-controls]'));
     const button=(zh,enText)=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes(en?enText:zh));
     if(mode==='missing'){
       for(const label of [['重新检测','Retry'],['选择已安装浏览器','Locate installed browser'],['官网下载 Edge','Official download Edge']]){button(...label).click();await new Promise(r=>setTimeout(r,20))}
       if(f.calls.map(c=>c.method).join(',')!=='retryBrowser,selectBrowser,openBrowserDownload'||f.calls[2].argument!=='edge')throw Error('Missing browser recovery controls failed');
     }else if(mode==='verification'){
       await wait(()=>f.calls.some(c=>c.argument?.automatic));await new Promise(r=>setTimeout(r,300));
       if(f.calls.filter(c=>c.argument?.automatic).length!==1)throw Error('Repeated automatic foreground request');
       button('打开浏览器完成验证','Open browser to verify').click();await new Promise(r=>setTimeout(r,40));
       if(!f.calls.some(c=>c.argument?.site==='nexus'&&!c.argument.automatic))throw Error('Manual verification button failed');
     }else{
       button('显示浏览器','Show browser').click();await new Promise(r=>setTimeout(r,25));
       if(mode==='failure'){if(!document.querySelector('[role=alert]'))throw Error('Failure hidden')}
       else {button('登录完成，收起','Done, minimize').click();await new Promise(r=>setTimeout(r,25));if(!f.calls.some(c=>c.method==='minimizeBrowser'))throw Error('Minimize button failed')}
       if(mode==='fallback'&&!document.body.textContent.includes(en?'separate sign-ins':'各自登录'))throw Error('Missing fallback profile notice');
     }
    })()`);
    if(['ready','missing'].includes(mode))fs.writeFileSync(path.join(root,`${mode}-${language}.png`),(await w.webContents.capturePage()).toPNG());
    results.push({language,mode,passed:true});
   }catch(e){results.push({language,mode,passed:false,error:e.message})}
  }
  for(const site of ['nexus','steam']){
   await w.loadFile(path.join(root,'chat.html'),{query:{browser_gate:site,language:'en'}});
   try{await w.webContents.executeJavaScript(`(async()=>{
     window.browserCalls=[];window.modagent={showBrowser:async o=>{window.browserCalls.push(o);return {ok:true}}};
     const wait=async pred=>{for(let i=0;i<150;i++){if(pred())return;await new Promise(r=>setTimeout(r,20))}throw Error('Chat gate timeout')};
     await wait(()=>document.querySelector('.chat-composer textarea'));
     const input=document.querySelector('.chat-composer textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'fixture request');input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,40));input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
     await wait(()=>window.browserCalls.length===1);if(window.browserCalls[0].site!==${JSON.stringify(site)}||!window.browserCalls[0].automatic)throw Error('Wrong verification request');
     if(window.fixtureRequests.filter(r=>r.url.endsWith('/chat/stream')).length!==1)throw Error('Verification replayed chat');
   })()`);results.push({site,mode:'actual-chat',passed:true})}catch(e){results.push({site,mode:'actual-chat',passed:false,error:e.message})}
  }
  fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(results,null,2));results.forEach(r=>console.log(JSON.stringify(r)));w.destroy();app.exit(results.every(r=>r.passed)?0:1);
 }).catch(e=>{console.error(e);app.exit(1)});
}
