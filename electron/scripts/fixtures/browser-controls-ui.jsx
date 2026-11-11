import React from 'react'
import {createRoot} from 'react-dom/client'
import BrowserControls from '../../src/components/BrowserControls'
import DownloadPanel from '../../src/components/DownloadPanel'
const q=new URLSearchParams(location.search),mode=q.get('mode')
window.fixture={calls:[],state:{phase:mode==='missing'?'missing':'ready',name:'Fixture Chrome',fallback:mode==='fallback'}}
window.modagent={getBrowserStatus:async()=>window.fixture.state}
for(const method of ['showBrowser','minimizeBrowser','retryBrowser','selectBrowser','openBrowserDownload'])window.modagent[method]=async argument=>{
  window.fixture.calls.push({method,argument})
  return {ok:mode!=='failure'}
}
window.fetch=async()=>new Response(JSON.stringify({active:true,generation:1,updated:Date.now()/1000,items:[{mod_id:1,name:'Fixture',status:'waiting_verification',phase:'waiting_verification',pct:0}],overall_pct:0}))
const timer=setTimeout.bind(window);window.setTimeout=(fn,ms,...args)=>timer(fn,ms===800?60:ms,...args)
createRoot(document.getElementById('root')).render(<><BrowserControls language={q.get('language')}/>{mode==='verification'&&<DownloadPanel api="http://fixture.invalid" language={q.get('language')}/>}</>)
