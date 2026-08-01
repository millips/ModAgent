const { spawnSync } = require('child_process')
const path = require('path')

const electronRoot = path.resolve(__dirname, '..')
const viteCli = path.join(
  path.dirname(require.resolve('vite/package.json')),
  'bin',
  'vite.js',
)

function normalizedEdition(value) {
  return value === 'free' ? 'free' : 'subscription'
}

function buildStepsForEdition(value) {
  const edition = normalizedEdition(value)
  const steps = []
  if (edition === 'subscription') {
    steps.push(['verify P audio', path.join(__dirname, 'verify-commercial-audio.js')])
  }
  steps.push(
    ['verify release text', path.join(__dirname, 'verify-release-text.js')],
    ['clean frontend output', path.join(__dirname, 'clean-dist.js')],
    ['build frontend', viteCli],
  )
  return { edition, steps }
}

function run() {
  const policy = buildStepsForEdition(process.env.MODAGENT_EDITION)
  console.log(`Building ModAgent frontend edition: ${policy.edition}`)
  for (const [label, script] of policy.steps) {
    const args = script.endsWith('vite.js') ? [script, 'build'] : [script]
    const result = spawnSync(process.execPath, args, {
      cwd: electronRoot,
      env: {
        ...process.env,
        MODAGENT_EDITION: policy.edition,
        // Keep the renderer marker in lockstep with electron-builder.  Without
        // this, a beta build silently produced a stable dist and the identity
        // guard correctly rejected the package as mixed-edition output.
        MODAGENT_CHANNEL: process.env.MODAGENT_CHANNEL || 'stable',
      },
      stdio: 'inherit',
    })
    if (result.error) throw result.error
    if (result.status !== 0) {
      throw new Error(`Frontend build step failed (${label}): exit ${result.status}`)
    }
  }
}

if (require.main === module) run()

module.exports = {
  buildStepsForEdition,
  normalizedEdition,
}
