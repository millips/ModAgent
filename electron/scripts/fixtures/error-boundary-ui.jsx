import React, {useState} from 'react'
import {createRoot} from 'react-dom/client'
import AppErrorBoundary from '../../src/components/AppErrorBoundary.jsx'
const query = new URLSearchParams(location.search)
const mode = query.get('mode')
document.documentElement.lang = query.get('language') || 'zh-CN'
const originalTimeout = window.setTimeout.bind(window)
window.setTimeout = (fn,ms,...args) => originalTimeout(fn,ms===15000?120:ms,...args)
localStorage.setItem('fixture-saved-settings','saved-only-fixture')
window.fixture = {opens:0,reloads:0,requests:0}
window.fetch = async () => {window.fixture.requests++; throw Error('Unexpected request')}
window.modagent = mode==='missing' ? {} : {openDiagnosticsFolder:async()=>{
  window.fixture.opens++
  if(mode==='timeout')return new Promise(()=>{})
  await new Promise(resolve=>originalTimeout(resolve,40))
  if(mode==='error')throw Error('private native path and token')
  return ''
}}
function Child() {
  const [failed,setFailed] = useState(mode==='initial')
  if(failed)throw Error('private render error and token')
  return <button onClick={()=>setFailed(true)}>Trigger fixture failure</button>
}
createRoot(document.getElementById('root')).render(<React.StrictMode><AppErrorBoundary onReload={()=>window.fixture.reloads++}><Child/></AppErrorBoundary></React.StrictMode>)
