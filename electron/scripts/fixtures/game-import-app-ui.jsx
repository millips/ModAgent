import React from 'react'
import {createRoot} from 'react-dom/client'
import App from '../../src/App'
const mode=new URLSearchParams(location.search).get('mode')
window.fixture={writes:0,scanReads:0,statusReads:0,active:{game_name:'Old Game',game_slug:'old',game_instance_id:'old-id',game_root:'X:/Old'}}
window.modagent={selectGameDirectory:async()=>({path:'X:/New',suggestedName:'New Game'})}
const timer=window.setTimeout.bind(window)
window.setTimeout=(fn,ms,...args)=>timer(fn,ms===120000?150:ms,...args)
window.fetch=async(url,options={})=>{
  const f=window.fixture
  const json=data=>new Response(JSON.stringify(data))
  if(url.endsWith('/health'))return json({ok:true})
  if(url.endsWith('/games/import')){
    f.writes++
    await new Promise(resolve=>{window.releaseImport=resolve})
    if(mode==='rejected'&&!f.retry)return new Response('{}',{status:400})
    if(mode==='timeout')return new Response(new ReadableStream({start(c){options.signal.addEventListener('abort',()=>c.error(new DOMException('Aborted','AbortError')))}}))
    f.active={game_name:'New Game',game_root:'X:/New',game_slug:'new',game_instance_id:'new-id'}
    return json({saved:true,game:{name:'New Game',path:'X:/New',slug:'new',game_instance_id:'new-id'},
      mod_scan:{game_instance_id:'new-id',status:'running',queued:true}})
  }
  if(url.endsWith('/status')){
    f.statusReads++
    if(mode==='recovery'&&f.writes&&!f.recovered)return new Response('{}',{status:503})
    return json({llm_model:'fixture',llm_endpoint:'https://fixture.invalid',llm_set:true,api_key_set:false,tavily_set:false,language:'en',...f.active})
  }
  if(url.includes('/mods/scan-status?')){
    f.scanReads++
    if(!url.endsWith('game_instance_id=new-id'))throw Error('Wrong scan scope')
    return json({game_instance_id:'new-id',status:'completed',detected:3,imported:2})
  }
  return json([])
}
createRoot(document.getElementById('root')).render(<App />)
