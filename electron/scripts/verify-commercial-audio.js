const packageInfo = require('../package.json')

const edition = process.env.MODAGENT_EDITION || packageInfo.modagentEdition || 'free'

if (edition === 'subscription') {
  console.error(
    'The public source tree does not include ModAgent P commercial audio or theme assets.'
  )
  process.exit(1)
}

console.log('Free edition selected; commercial audio verification is not required.')

module.exports = {
  expectedAudioCount: 0,
}
