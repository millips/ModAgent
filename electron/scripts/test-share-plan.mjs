import assert from 'node:assert/strict'
import {sharePlanPrompt,sharePrerequisitesPending} from '../src/components/sharePlan.mjs'
import {validateOfficialPreview} from '../src/components/officialShareResponse.mjs'
const preview={items:[{name:'Fixture'}],summary:{total:1},source_kind:'official_collection',official:{id:'ma-fixture'}}
assert.equal(validateOfficialPreview(preview,'ma-fixture'),preview)
for(const bad of [{...preview,official:{id:'ma-other'}},{...preview,official:{}},{...preview,source_kind:'private'}])assert.throws(()=>validateOfficialPreview(bad,'ma-fixture'))
for(const status of ['satisfied_installed','satisfied_base_environment','included_collection'])assert.equal(sharePrerequisitesPending({summary:{host_dependency_requirements:[{status}]}}),false)
assert.equal(sharePrerequisitesPending({summary:{host_dependency_requirements:[{status:'needs_external_resolution'}]}}),true)
assert.equal(sharePlanPrompt({},'en'),'')
for(const language of ['en','zh-CN'])for(const official of [false,true])for(const prerequisite of [false,true]){
  const request=official?{shareId:'ma-fixture'}:{share:'fixture share'}
  request.action=prerequisite?'prerequisite_plan':'install_plan'
  const prompt=sharePlanPrompt(request,language)
  assert.ok(prompt.includes(official?'ma-fixture':'fixture share'))
  assert.ok(prompt.includes(language==='en'?(prerequisite?'Do not install the main Mods':'Do not install directly'):(prerequisite?'不得安装主体 Mod':'不要直接安装')))
  if(language==='en')assert.ok(!/[\u4e00-\u9fff]/.test(prompt))
}
console.log('SHARE PLAN PASSED: official identity, prerequisite routing, bilingual non-installing prompts, empty request')
