const assert = require('assert')
const { getAppIdentity } = require('../appIdentity')

function identity(edition, channel) {
  const previousEdition = process.env.MODAGENT_EDITION
  const previousChannel = process.env.MODAGENT_CHANNEL
  process.env.MODAGENT_EDITION = edition
  process.env.MODAGENT_CHANNEL = channel
  try {
    return getAppIdentity({ version: '1.3.0' })
  } finally {
    if (previousEdition === undefined) delete process.env.MODAGENT_EDITION
    else process.env.MODAGENT_EDITION = previousEdition
    if (previousChannel === undefined) delete process.env.MODAGENT_CHANNEL
    else process.env.MODAGENT_CHANNEL = previousChannel
  }
}

const stable = identity('subscription', 'stable')
const beta = identity('subscription', 'beta')

assert.strictEqual(stable.productName, 'ModAgent P')
assert.strictEqual(stable.appId, 'com.modagent.desktop.pro')
assert.strictEqual(stable.updateChannel, 'subscription')
assert.strictEqual(beta.productName, 'ModAgent P Beta')
assert.strictEqual(beta.executableName, 'ModAgentPBeta')
assert.strictEqual(beta.appId, 'com.modagent.desktop.pro.beta')
assert.strictEqual(beta.userDataFolder, 'ModAgent P Beta')
assert.strictEqual(beta.artifactPrefix, 'ModAgent-P-Beta')
assert.strictEqual(beta.updateChannel, 'subscription-beta')
assert.notStrictEqual(beta.appId, stable.appId)
assert.notStrictEqual(beta.userDataFolder, stable.userDataFolder)

console.log('APP IDENTITY TESTS PASSED')
