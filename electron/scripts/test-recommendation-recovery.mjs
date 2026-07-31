import assert from 'node:assert/strict'
import { hasSameRecommendation } from '../src/components/recommendationRecovery.mjs'

const oldPayload = {
  anchor_after_text_count: 3,
  items: [{ selection_key: 'nexus:1' }],
}
const currentPayload = {
  anchor_after_text_count: 7,
  items: [{ selection_key: 'nexus:2' }],
}
const messages = [
  { role: 'edition', payload: oldPayload },
]

assert.equal(
  hasSameRecommendation(messages, currentPayload),
  false,
  'an older decision table must not suppress the current recovered table',
)
assert.equal(
  hasSameRecommendation(messages, oldPayload),
  true,
  'an exact replay of the same recovered table must be deduplicated',
)
assert.equal(
  hasSameRecommendation(messages, {
    ...oldPayload,
    anchor_after_text_count: 9,
  }),
  false,
  'the same candidates from a later user request are a new decision table',
)

console.log('ALL PASS')
