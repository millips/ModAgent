import assert from 'node:assert/strict'
import {validateDownloadStatus, progressPercent} from '../src/components/downloadStatus.mjs'
const state = {active:true,generation:1,updated:1,overall_pct:25,cancel_requested:false,items:[{status:'downloading',mod_id:'a',pct:25,detail:'Downloading'}]}
assert.equal(validateDownloadStatus(state),state)
assert.doesNotThrow(()=>validateDownloadStatus({...state,items:[],active:false}))
assert.doesNotThrow(()=>validateDownloadStatus({...state,items:[{status:'future_status',phase:'future_phase'}]}))
let rejected = 0
for (const patch of [
  {active:'true'}, {generation:-1}, {generation:1.2}, {generation:Number.MAX_SAFE_INTEGER+1},
  {updated:null}, {updated:NaN}, {overall_pct:Infinity}, {overall_pct:'25'},
  {cancel_requested:'false'}, {elapsed_seconds:{}}, {eta_seconds:'5'}, {label:{}},
  {current_item:[]}, {current_item:{phase:{}}}, {items:[null]}, {items:[[]]},
  {items:[{status:{}}]}, {items:[{status:'failed',error:{message:'private'}}]},
  {items:[{status:'processing',detail:{}}]}, {items:[{status:'processing',phase_label:{}}]},
  {items:[{status:'queued',pct:NaN}]}, {items:[{status:'queued',mod_id:{}}]},
]) {
  assert.throws(()=>validateDownloadStatus({...state,...patch}),/^Error: DOWNLOAD_STATUS_INVALID$/)
  rejected++
}
for(const [input, expected] of [[undefined,0],[Infinity,0],[NaN,0],[-10,0],[140,100],[35.5,35.5]])assert.equal(progressPercent(input),expected)
console.log(`Download status: ${rejected} malformed payloads rejected; valid/unknown states and bounded percentages passed`)
