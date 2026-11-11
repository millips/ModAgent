import assert from 'node:assert/strict'
import {parseManualSourceUrl as parse,validateSourceReceipt} from '../src/components/manualSource.mjs'
assert.equal(parse('https://www.nexusmods.com/game/mods/123').source_key,'123')
assert.equal(parse('https://thunderstore.io/c/repo/p/Team/Package/').source_key,'Team-Package')
for (const url of ['https://evilnexusmods.com/mods/123','https://evilthunderstore.io/c/repo/p/A/B/','http://nexusmods.com/mods/123','https://user:password@nexusmods.com/mods/123','https://thunderstore.io/c/repo/p/%E0%A4/B/','not a URL']) assert.equal(parse(url),null,url)
console.log('MANUAL SOURCE PASSED: supported pages, deceptive domains, credentials, non-HTTPS and malformed escapes')
const candidate={source:'nexus',source_key:'123'}
const preview={local:{mod_id:'local'},nexus:{mod_id:123,name:'Fixture',version:'1'}}
const validate=(result,confirmed=false)=>validateSourceReceipt({result:JSON.stringify(result)},'local',candidate,confirmed)
assert.equal(validate({requires_confirmation:true,preview}).preview.nexus.name,'Fixture')
assert.equal(validate({bound:true,source:'nexus',source_key:'123',preview},true).bound,true)
for(const result of [null,[],{}, {requires_confirmation:'true',preview},
  {requires_confirmation:true,preview:{...preview,local:{mod_id:'other'}}},
  {requires_confirmation:true,preview:{...preview,nexus:{...preview.nexus,mod_id:456}}},
  {requires_confirmation:true,preview:{...preview,nexus:{...preview.nexus,name:{}}}}]){
  assert.throws(()=>validate(result),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
}
for(const result of [{bound:'true',source:'nexus',source_key:'123',preview},
  {bound:true,source:'nexus',source_key:'456',preview},
  {bound:true,source:'thunderstore',source_key:'123',preview}]){
  assert.throws(()=>validate(result,true),e=>e.code==='LOCAL_API_INVALID_RESPONSE')
}
const thunder={source:'thunderstore',source_key:'Team-Package'}
const thunderPreview={local:{mod_id:'local'},source:{kind:'thunderstore',source_key:'Team-Package',name:'Fixture',version:'',url:'https://thunderstore.io/c/repo/p/Team/Package/'}}
assert.ok(validateSourceReceipt({result:JSON.stringify({requires_confirmation:true,preview:thunderPreview})},'local',thunder))
thunderPreview.source.url='https://evilthunderstore.io/c/repo/p/Team/Package/'
assert.throws(()=>validateSourceReceipt({result:JSON.stringify({requires_confirmation:true,preview:thunderPreview})},'local',thunder))
console.log('SOURCE RECEIPT PASSED: strict flags, local/source identities, safe render fields, both sources')
