import assert from 'node:assert/strict'
import { canPresentConfirmation, canCompleteSelection, apiErrorMessage, receiptProgress } from '../src/components/taskOutcome.mjs'

const good = { streamCompleted: true, streamFailed: false, executionFailed: false, planBlocked: false }
assert.equal(canPresentConfirmation(good), true)
for (const flag of ['streamFailed', 'executionFailed', 'planBlocked']) {
  assert.equal(canPresentConfirmation({ ...good, [flag]: true }), false, flag)
  assert.equal(canCompleteSelection({ ...good, [flag]: true, executionVerified: true, selectionAction: 'confirm' }), false, flag)
}
assert.equal(canCompleteSelection({ ...good, selectionAction: 'confirm' }), false, 'done SSE alone cannot prove installation')
assert.equal(canCompleteSelection({ ...good, selectionAction: 'confirm', executionVerified: true }), true)
assert.equal(canCompleteSelection({ ...good, selectionAction: 'plan' }), true)
assert.equal(apiErrorMessage({ detail: { code: 'plan_revalidation_required', message: '重新核验计划' } }, 'failed'), '重新核验计划')
assert.equal(apiErrorMessage({}, 'failed'), 'failed')
assert.match(receiptProgress({ ok: true, outcome_status: 'waiting_user' }, '下载', 'zh-CN'), /等待用户处理/)
assert.match(receiptProgress({ ok: false, outcome_status: 'failed' }, '下载', 'zh-CN'), /未完成/)
assert.match(receiptProgress({ ok: true, outcome_status: 'success' }, '下载', 'en'), /step completed/)
console.log('task outcome tests passed')
