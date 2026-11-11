const path=require('node:path'),fs=require('node:fs');
const root=path.resolve(__dirname,'../../build/v17-settings-save-ui');
if(!process.versions.electron){
  const result=require('node:child_process').spawnSync(require('electron'),[__filename],{encoding:'utf8',timeout:20000,windowsHide:true});
  process.stdout.write(result.stdout||'');process.stderr.write(result.stderr||'');
  if(result.error)throw result.error;process.exit(result.status??1);
}else{
  const {app,BrowserWindow,session}=require('electron');app.setPath('userData',path.join(root,'language-profile'));
  app.whenReady().then(async()=>{
    session.defaultSession.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_,cb)=>cb({cancel:true}));
    const win=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
    await win.loadFile(path.join(root,'index.html'),{query:{mode:'language-keys'}});
    await win.webContents.executeJavaScript(`(async()=>{
      const wait=async fn=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,20))}throw Error('Language condition failed')};
      const text=()=>document.body.textContent;
      await wait(()=>text().includes('Provider presets'));
      if([...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='Replace key').length!==3)throw Error('Key replacement labels missing');
      if([...document.querySelectorAll('input[type=password]')].some(i=>i.placeholder!=='Configured'||!i.disabled))throw Error('Configured key status changed');
      const custom=[...document.querySelectorAll('input')].find(i=>i.placeholder.includes('provider documentation'));
      if(!custom)throw Error('Missing custom model guidance');
      const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
      setter.call(custom,'my-unsaved-model');custom.dispatchEvent(new Event('input',{bubbles:true}));
      const cards=[...document.querySelectorAll('.card-cyber')].filter(card=>card.querySelector('input[type=password]')||card.textContent.includes('Provider presets')||card.querySelector('#recommendation-limit')||card.querySelector('[role=radiogroup]'));
      if(cards.length!==4)throw Error('Core settings audit scope missing');
      for(const card of cards){
        const visible=card.textContent+[...card.querySelectorAll('[placeholder],[aria-label]')].map(e=>(e.placeholder||'')+(e.getAttribute('aria-label')||'')).join('');
        if(/[\\u4e00-\\u9fff]/.test(visible))throw Error('Untranslated core settings text');
      }
      window.fixture.switchLanguage('zh-CN');await wait(()=>text().includes('服务商快捷预设'));
      for(const phrase of ['自定义模型名','接口地址','智能推荐','界面布局','朴素版','设计版'])if(!text().includes(phrase))throw Error('Chinese text lost: '+phrase);
      if(custom.value!=='my-unsaved-model'||!custom.isConnected)throw Error('Language switch lost draft');
      window.fixture.switchLanguage('en');await wait(()=>text().includes('Provider presets'));
      if(custom.value!=='my-unsaved-model'||!text().includes('Maximum candidates'))throw Error('Switch back failed');
      if(window.fixture.stores||window.fixture.requests.some(r=>r.url.endsWith('/config')))throw Error('Language preview wrote settings');
    })()`);
    fs.writeFileSync(path.join(root,'language-result.json'),JSON.stringify({passed:true,scope:'core credential/model/recommendation/layout text; en-zh-en; unsaved draft; no persistence'},null,2));
    console.log('SETTINGS LANGUAGE PASSED: core labels/placeholders, en-zh-en switching, draft preserved, zero config writes');win.destroy();app.exit(0);
  }).catch(error=>{console.error(error);app.exit(1)});
}
