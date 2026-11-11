import assert from 'node:assert/strict'
import {installedShareVersionLabel as label,validateSharePreview,shareFileStateLabel as state} from '../src/components/shareResponse.mjs'
const item={name:'a',status:'already_installed',version:'1',installed_match:{version:'2'}}
assert.match(label(item,'en'),/Version differs/)
assert.match(label(item,'zh-CN'),/版本不同/)
assert.match(label({...item,installed_match:{version:'1'}},'zh-CN'),/记录版本相同/)
assert.match(label({...item,version:''},'zh-CN'),/尚无法核对/)
for(const bad of [{...item,version:{}},{...item,installed_match:{version:{}}},{...item,installed_match:[]}])assert.throws(()=>validateSharePreview({items:[bad],summary:{total:1}}))
console.log('Share version bilingual labels and malformed version rejection passed')
assert.match(state({file_state:'enabled_files',installed_match:{file_state:'disabled_files'}},'en'),/differs/)
assert.match(state({file_state:'enabled_files',installed_match:{file_state:'enabled_files'}},'zh-CN'),/相同/)
assert.match(state({enabled:true,installed_match:{}},'en'),/unavailable/)
assert.match(state({file_state:'toString',installed_match:{file_state:'constructor'}},'en'),/unavailable/)
