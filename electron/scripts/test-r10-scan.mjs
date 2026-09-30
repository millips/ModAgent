import assert from 'node:assert/strict'
import { scanInventory } from '../src/components/scanInventory.mjs'
for (const [data, ok] of [
  [{ identified: [], imported: 0, detected: 129 }, true],
  [{ identified: [{}], imported: 1 }, true],
  [{ identified: [], status: 'blocked' }, false],
  [{ error: 'fixture' }, false], [null, false],
]) {
  const toasts = [], feedback = []; let refresh = 0
  const result = await scanInventory({ api: '', fetchImpl: async () => ({ok:true,json:async()=>({result:JSON.stringify(data)})}),
    toast: (...args)=>toasts.push(args), emitFeedback: (...args)=>feedback.push(args), onRefresh: ()=>{refresh++} })
  assert.equal(result.ok, ok); assert.equal(refresh, 1)
  assert.equal(feedback.some(([name])=>name==='scan-complete'), ok)
  assert(!toasts.some(([text])=>text.includes('未检测到新 Mod')))
}
console.log('5 scan receipt and refresh scenarios passed')
