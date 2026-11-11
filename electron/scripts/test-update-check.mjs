import assert from 'node:assert/strict'
import {checkDesktopUpdate} from '../src/updateCheck.mjs'
const run = result => checkDesktopUpdate({checkForAppUpdate:async()=>result})
assert.deepEqual(await run({ok:true,disabled:true,available:false}),{disabled:true})
for(const available of [true,false])assert.equal((await run({ok:true,available,version:'1.7.0-beta.1'})).available,available)
for(const result of [{},{ok:false,error:'private error'},{ok:true},{ok:true,version:'1.7.0'},{ok:true,available:false,version:'broken'}])await assert.rejects(run(result))
await assert.rejects(checkDesktopUpdate({}),/UPDATE_UNAVAILABLE/)
await assert.rejects(checkDesktopUpdate({checkForAppUpdate:()=>new Promise(()=>{})},10),/UPDATE_TIMEOUT/)
console.log('UPDATE CHECK PASSED: disabled is not current, explicit availability and version required, errors and deadlines')
