const assert = require('assert')
const path = require('path')
const {
  buildStepsForEdition,
  normalizedEdition,
} = require('./build-frontend')

function names(policy) {
  return policy.steps.map(([, script]) => path.basename(script))
}

assert.strictEqual(normalizedEdition('free'), 'free')
assert.strictEqual(normalizedEdition('subscription'), 'subscription')
assert.strictEqual(normalizedEdition(undefined), 'subscription')

const free = buildStepsForEdition('free')
assert.strictEqual(free.edition, 'free')
assert.deepStrictEqual(names(free), [
  'verify-release-text.js',
  'clean-dist.js',
  'vite.js',
])

const subscription = buildStepsForEdition('subscription')
assert.strictEqual(subscription.edition, 'subscription')
assert.deepStrictEqual(names(subscription), [
  'verify-commercial-audio.js',
  'verify-release-text.js',
  'clean-dist.js',
  'vite.js',
])

console.log('FRONTEND BUILD POLICY TESTS PASSED')
