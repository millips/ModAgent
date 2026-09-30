import assert from 'node:assert/strict'
import { upsertTaskResult, taskPresentation, precedingAnswer } from '../src/components/taskPresentation.mjs'
const event = (state, summary, extra = {}) => ({ task_id: 't1', seq: 2, type: state === 'COMPLETED' ? 'task_completed' : 'task_failed', state, payload: { result: { summary, completed: [], not_completed: [], ...extra } } })
const answer = '**Mod** 是游戏修改。'.repeat(100)
assert.equal(taskPresentation(event('COMPLETED', answer), answer).hidden, true)
assert.equal(taskPresentation(event('COMPLETED', answer.slice(0, 800)), answer).hidden, true)
assert.equal(taskPresentation(event('COMPLETED', answer.slice(0, 799) + '…'), answer).hidden, true)
assert.equal(taskPresentation(event('FAILED', answer), answer).hidden, false)
assert.equal(taskPresentation(event('COMPLETED', answer, { warnings: ['warning'] }), answer).hidden, false)
assert.equal(taskPresentation(event('COMPLETED', answer, { completed: [{ tool: 'nexus_search' }] }), answer).hidden, false)
const compact = event('COMPLETED', '已回答。')
compact.payload.presentation = { show_card: false }
assert.equal(taskPresentation(compact, answer).hidden, true)
assert.equal(taskPresentation(compact, '').hidden, false, 'never hide the only visible result')
assert.equal(taskPresentation(event('BLOCKED', '尚未搜索')).showCounts, false)
assert.equal(taskPresentation(event('PARTIAL', '部分成功', { completed: [{}] })).showCounts, true)
let messages = [{ role: 'user', content: 'hello' }, { role: 'agent', content: answer }]
messages = upsertTaskResult(messages, compact)
assert.equal(messages.length, 3)
assert.equal(upsertTaskResult(messages, compact), messages, 'replay is idempotent')
assert.equal(upsertTaskResult(messages, { ...compact, seq: 1 }), messages, 'older results cannot replace newer ones')
assert.equal(precedingAnswer(messages, 2), answer)
assert.equal(precedingAnswer([...messages, { role: 'user', content: '?' }, { role: 'task-result' }], 4), '')
console.log('15 task presentation checks passed')
