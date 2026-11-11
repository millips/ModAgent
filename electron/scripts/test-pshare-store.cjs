const assert = require('node:assert/strict')
const vm = require('node:vm')
const path = require('node:path')
const code = require('esbuild').buildSync({entryPoints:[path.join(__dirname,'../src/pshare/pShareStore.js')],bundle:true,write:false,platform:'node',format:'cjs',external:['react']}).outputFiles[0].text
const values = new Map()
let notifications = 0, fail = false
const context = {
  module:{exports:{}}, require,
  CustomEvent:class {constructor(type){this.type=type}},
  window:{localStorage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>{if(fail)throw Error('storage unavailable');values.set(key,value)}},dispatchEvent:()=>notifications++},
}
vm.runInNewContext(code,context)
const store = context.module.exports
assert.equal(store.upsertPShareSubmission({title:'missing ID'}), null)
assert.equal(notifications,0)
const first = store.upsertPShareSubmission({submission_id:'one',title:'Original',status:'submission_opened',created_at:'2026-01-01T00:00:00Z',issue_url:'https://example.invalid/issue',mod_count:3})
assert.equal(first.status,'submission_opened')
const changed = store.upsertPShareSubmission({submission_id:'one',title:'Edited',created_at:'unexpected replacement',updated_at:'stale timestamp'})
assert.equal(changed.created_at,first.created_at)
assert.equal(changed.status,first.status)
assert.equal(changed.issue_url,first.issue_url)
assert.equal(changed.mod_count,3)
assert.notEqual(changed.updated_at,'stale timestamp')
assert.equal(store.readPShareSubmissions().length,1)
assert.equal(store.readPShareSubmissions()[0].title,'Edited')
const second = store.upsertPShareSubmission({submission_id:'two'})
assert.equal(second.status,'draft')
assert.equal(store.readPShareSubmissions()[0].submission_id,'two')
store.updatePShareSubmission('one',{warning:'Check attachment'})
assert.equal(store.readPShareSubmissions()[1].status,'submission_opened')
assert.equal(store.updatePShareSubmission('missing',{}),null)
const before = JSON.stringify(store.readPShareSubmissions()), count = notifications
fail = true
assert.throws(()=>store.upsertPShareSubmission({submission_id:'one',title:'not saved'}),/storage unavailable/)
assert.equal(JSON.stringify(store.readPShareSubmissions()),before)
assert.equal(notifications,count)
console.log('PShare store passed: preserve existing metadata, unique IDs, timestamps, defaults, failed write without success notification')
