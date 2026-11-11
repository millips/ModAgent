import assert from 'node:assert/strict'
import {runMaintenanceAction,maintenanceFailure} from '../src/maintenanceActions.mjs'
const calls=[]
const bridge={openDiagnosticsFolder:async()=>{calls.push('logs');return ''},openMaintenanceFolder:async kind=>{calls.push(kind);return ''},copyMaintenancePath:async kind=>{calls.push('copy:'+kind);return {ok:true}}}
for(const kind of ['logs','data','cache','copyLogs'])await runMaintenanceAction(kind,{bridge})
assert.deepEqual(calls,['logs','data','cache','copy:logs'])
await assert.rejects(runMaintenanceAction('logs',{bridge:{}}),/MAINTENANCE_UNAVAILABLE/)
for(const result of ['private path error',undefined,true])await assert.rejects(runMaintenanceAction('logs',{bridge:{openDiagnosticsFolder:async()=>result}}),/MAINTENANCE_FAILED/)
await assert.rejects(runMaintenanceAction('copyLogs',{bridge:{copyMaintenancePath:async()=>({ok:false})}}),/MAINTENANCE_FAILED/)
await assert.rejects(runMaintenanceAction('logs',{bridge:{openDiagnosticsFolder:()=>{throw Error('private-secret')} }}),error=>error.message==='MAINTENANCE_FAILED')
let complete
await assert.rejects(runMaintenanceAction('logs',{timeoutMs:10,bridge:{openDiagnosticsFolder:()=>new Promise(resolve=>{complete=resolve})}}),/MAINTENANCE_TIMEOUT/)
complete('')
assert.match(maintenanceFailure(Error('MAINTENANCE_TIMEOUT'),'en'),/may still/)
assert.match(maintenanceFailure(Error('MAINTENANCE_TIMEOUT'),'zh-CN'),/稍后更新/)
assert(!maintenanceFailure(Error('private-secret'),'en').includes('private-secret'))
console.log('MAINTENANCE PASSED: all routes, strict receipts, unavailable bridge, redaction, deadline, late completion, bilingual uncertainty')
