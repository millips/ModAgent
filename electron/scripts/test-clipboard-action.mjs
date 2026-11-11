import assert from 'node:assert/strict'
import {writeClipboardText,clipboardFailure} from '../src/clipboardAction.mjs'
let copied
await writeClipboardText('fixture',{writeText:async text=>{copied=text}})
assert.equal(copied,'fixture')
await assert.rejects(writeClipboardText('',{writeText:()=>assert.fail('empty write')}),/COPY_EMPTY/)
await assert.rejects(writeClipboardText('fixture',{}),/COPY_UNAVAILABLE/)
await assert.rejects(writeClipboardText('fixture',{writeText:()=>{throw Error('private detail')}}),/COPY_FAILED/)
let finish
await assert.rejects(writeClipboardText('fixture',{writeText:()=>new Promise(resolve=>{finish=resolve})},10),/COPY_TIMEOUT/)
finish()
assert.match(clipboardFailure(Error('COPY_TIMEOUT'),'en'),/may update later/)
assert.match(clipboardFailure(Error('COPY_TIMEOUT'),'zh-CN'),/稍后更新/)
assert(!clipboardFailure(Error('private detail'),'en').includes('private detail'))
console.log('CLIPBOARD PASSED: acknowledged write, empty/unavailable/denied, deadline, late completion, bilingual uncertainty')
