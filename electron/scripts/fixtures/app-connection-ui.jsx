import React from 'react'
import {createRoot} from 'react-dom/client'
import App from '../../src/App'
const mode=new URLSearchParams(location.search).get('mode')
window.fixture={statusReads:0,gameWrites:0,activeGame:{}}
const timer=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>timer(fn,[15000,120000].includes(ms)?150:ms,...args)
window.fetch=async(url,options={})=>{
  if(window.fixture.offline)throw new Error('fixture offline')
  if(url.endsWith('/games/import')){
    window.fixture.gameWrites++
    if(mode==='import-rejected')return new Response('{}',{status:400})
    if(mode==='import-http')return new Response('{}',{status:503})
    if(mode==='import-invalid')return new Response('{}')
    if(mode==='import-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    const game={name:'Imported Game',path:'C:/fixture/import',slug:'imported',game_instance_id:'import-id'}
    if(mode!=='import-mismatch')window.fixture.activeGame={game_name:game.name,game_root:game.path,game_slug:game.slug,game_instance_id:game.game_instance_id}
    return new Response(JSON.stringify({saved:true,game,mod_scan:{queued:true}}))
  }
  if(url.endsWith('/config') && mode.startsWith('select-')){
    window.fixture.gameWrites++
    await new Promise(resolve=>{window.fixture.releaseSelection=resolve})
    if(mode==='select-http')return new Response('{}',{status:503})
    if(mode==='select-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    if(mode==='select-invalid')return new Response('{}')
    if(mode!=='select-mismatch')window.fixture.activeGame=JSON.parse(options.body)
    return new Response('{"ok":true}')
  }
  if(url.endsWith('/health'))return new Response('{"ok":true}')
  if(url.endsWith('/status')){
    window.fixture.statusReads++
    if(mode.includes('recovery')&&window.fixture.gameWrites>0){
      window.fixture.recoveryReads=(window.fixture.recoveryReads||0)+1
      if(window.fixture.recoveryReads===1||(mode.endsWith('retry')&&window.fixture.recoveryReads===2))return new Response('{}',{status:503})
    }
    if(window.fixture.statusReads===1){
      if(mode==='status-http')return new Response('{}',{status:503})
      if(mode==='status-invalid')return new Response('{}')
      if(mode==='status-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    }
    return new Response(JSON.stringify({llm_model:'fixture',llm_endpoint:'https://fixture.invalid',llm_set:mode!=='unconfigured',api_key_set:false,tavily_set:false,language:'en',...window.fixture.activeGame}))
  }
  if(url.endsWith('/mods')){
    if(mode==='counts-http')return new Response('{}',{status:503})
    if(mode==='counts-invalid')return new Response('{}')
    if(mode==='counts-body')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    return new Response('[{"id":"one"}]')
  }
  return new Response('[]')
}
createRoot(document.getElementById('root')).render(<App />)
