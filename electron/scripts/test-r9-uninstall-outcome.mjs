import assert from 'node:assert/strict'
import { uninstallOutcome } from '../src/components/uninstallOutcome.mjs'

for (const data of [
  {}, null, { status: 'partial', removed: 2 }, { status: 'cancelled' },
  { status: 'blocked', unsubscribed: false }, { record_retained: true, removed: 2 },
  { status: 'completed', details: { errors: ['locked'] } },
  { status: 'completed', external_config_cleanup: { complete: false } },
  { requires_confirmation: true }, { removed: 0, details: { blocked_unsafe: ['outside'] } },
]) assert.equal(uninstallOutcome(data).complete, false, JSON.stringify(data))
for (const data of [{ status: 'completed', removed: 2 }, { removed: 0 }, { unsubscribed: true }]) {
  assert.equal(uninstallOutcome(data).complete, true)
}
assert.match(uninstallOutcome({ status: 'partial' }, 'en').message, /not fully confirmed/)
assert.match(uninstallOutcome({ record_retained: true }).message, /未全部确认/)
console.log('15 uninstall outcome checks passed')
