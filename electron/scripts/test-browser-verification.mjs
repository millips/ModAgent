import assert from 'node:assert/strict'
import {browserVerificationSite} from '../src/components/browserVerification.mjs'
assert.equal(browserVerificationSite({name:'mod_download',status:'manual_action_required'}),'nexus')
assert.equal(browserVerificationSite({name:'batch_download',status:'partial_manual_action_required'}),'nexus')
assert.equal(browserVerificationSite({name:'workshop_install',status:'login_required'}),'steam')
assert.equal(browserVerificationSite({name:'mod_download',status:'retryable_site_error'}),null)
assert.equal(browserVerificationSite({name:'mod_download',summary:'please sign in',preview:'{"status":"manual_action_required"}'}),null)
assert.equal(browserVerificationSite({name:'unknown',status:'login_required'}),null)
console.log('BROWSER VERIFICATION EVENT GATES PASSED')
