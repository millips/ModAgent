import assert from 'node:assert/strict'
import {credentialPromptForTool as prompt} from '../src/components/credentialPrompt.mjs'
assert.equal(prompt({name:'mod_download',status:'nexus_api_key_missing'}),'nexus')
assert.equal(prompt({name:'batch_download',status:'nexus_api_key_missing'}),'nexus')
assert.equal(prompt({name:'nexus_search',ok:false},{tavily_set:false}),'tavily')
assert.equal(prompt({name:'nexus_search',ok:true},{tavily_set:false}),null)
assert.equal(prompt({name:'nexus_search',ok:false},{tavily_set:true}),null)
assert.equal(prompt({name:'nexus_search',ok:false},{}),null)
assert.equal(prompt({name:'mod_download',summary:'nexus_api_key_missing',preview:'nexus_api_key_missing'}),null)
assert.equal(prompt({name:'unknown',status:'nexus_api_key_missing'}),null)
assert.equal(prompt(null),null)
console.log('Credential prompts: structured events only; optional search not forced; unknown status ignored')
