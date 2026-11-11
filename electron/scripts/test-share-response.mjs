import assert from 'node:assert/strict'
import {readShareResult,validateSharePreview,validateShareExport} from '../src/components/shareResponse.mjs'
const good={items:[{name:'Fixture',status:'needs_source_resolution'}],summary:{total:1},game:{slug:'fixture'}}
assert.deepEqual(validateSharePreview(readShareResult({result:JSON.stringify(good)})),good)
for(const result of [undefined,'bad','null','[]','{}']) {
  assert.throws(()=>validateSharePreview(readShareResult({result})))
}
for(const value of [{...good,items:{}},{...good,summary:{total:2}},{...good,items:[{name:{}}]},{...good,summary:{total:1,host_dependency_requirements:{}}}])assert.throws(()=>validateSharePreview(value))
assert.throws(()=>readShareResult({result:'{"error":"secret"}'}), e=>e.code==='SHARE_VERIFICATION_REJECTED'&&!e.message.includes('secret'))
assert.equal(validateShareExport({share_json:'{"mods":[{}]}'},1).share_json,'{"mods":[{}]}')
for(const share_json of [undefined,'null','bad','{}','{"mods":[]}'])assert.throws(()=>validateShareExport({share_json},1))
console.log('SHARE RESPONSE PASSED: valid result, malformed envelope, malformed preview, rejected share, export count integrity')
