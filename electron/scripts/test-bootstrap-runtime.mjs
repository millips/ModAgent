import assert from 'node:assert/strict'
import { startRenderer } from '../src/bootstrapRuntime.mjs'

function fixture() {
  const element = () => ({style:{},children:[],attributes:{},textContent:'',setAttribute(key,value){this.attributes[key]=value},appendChild(value){this.children.push(value)},replaceChildren(...values){this.children=values},addEventListener(type,fn){this[type]=fn}})
  const root = element()
  return {root,documentRef:{getElementById:()=>root,createElement:element}}
}
for(const mode of ['success','load-error','invalid-module','mount-error','timeout']) {
  const {root,documentRef} = fixture()
  let mounted=0,reloaded=0,resolveLate
  const load=()=>{
    if(mode==='load-error')throw Error('private startup token')
    if(mode==='invalid-module')return {}
    if(mode==='timeout')return new Promise(resolve=>{resolveLate=resolve})
    return {mountApp(){mounted++;if(mode==='mount-error')throw Error('private path')}}
  }
  const ok=await startRenderer({load,timeoutMs:10,documentRef,reload:()=>reloaded++})
  assert.equal(ok,mode==='success')
  assert.equal(reloaded,0)
  if(mode==='success')assert.equal(root.children.length,0)
  else {
    const panel=root.children[0],text=panel.children.map(item=>item.textContent).join(' ')
    assert.equal(panel.attributes.role,'alert')
    assert(text.includes(mode==='timeout'?'UI_STARTUP_TIMEOUT':'UI_STARTUP_FAILED'))
    assert(text.includes('后台任务可能仍在运行')&&text.includes('Background tasks may still be running'))
    assert(!text.includes('private'))
    panel.children.at(-1).click()
    assert.equal(reloaded,1)
  }
  if(resolveLate){resolveLate({mountApp(){mounted++}});await new Promise(resolve=>setTimeout(resolve,0));assert.equal(mounted,0,'Late module must not replace recovery UI')}
}
console.log('Bootstrap runtime: success, load failure, invalid module, mount failure, timeout and late completion passed')
