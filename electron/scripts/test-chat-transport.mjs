import assert from 'node:assert/strict'
import { createChatWatchdog, chatTimeoutMessage, CHAT_IDLE_TIMEOUT_MS } from '../src/components/chatTransport.mjs'

function fixture() {
  let now = 0, nextId = 0
  const timers = new Map()
  const controller = new AbortController()
  const watchdog = createChatWatchdog(controller, {
    schedule(fn, ms) { const id = ++nextId; timers.set(id, {fn, at: now+ms}); return id },
    cancel(id) { timers.delete(id) },
  })
  return {controller, watchdog, timers, advance(ms) {
    now += ms
    for(const [id, timer] of [...timers]) if(timer.at <= now) { timers.delete(id); timer.fn() }
  } }
}
{
  const f=fixture()
  f.advance(CHAT_IDLE_TIMEOUT_MS-1)
  assert.equal(f.controller.signal.aborted, false)
  f.advance(1)
  assert.equal(f.controller.signal.aborted, true)
  assert.equal(f.watchdog.timedOut, true)
  assert.equal(f.timers.size, 0)
}
{
  const f=fixture()
  // A five-minute active task remains connected with heartbeats.
  for(let i=0;i<30;i++) { f.advance(10000); f.watchdog.touch() }
  assert.equal(f.controller.signal.aborted, false)
  f.advance(CHAT_IDLE_TIMEOUT_MS)
  assert.equal(f.watchdog.timedOut, true)
}
{
  const f=fixture()
  f.controller.abort()
  f.advance(CHAT_IDLE_TIMEOUT_MS)
  assert.equal(f.watchdog.timedOut, false, 'User cancellation is not a network failure')
  f.watchdog.touch()
  assert.equal(f.timers.size, 0)
}
{
  const f=fixture()
  f.watchdog.dispose(); f.watchdog.dispose(); f.watchdog.touch()
  f.advance(CHAT_IDLE_TIMEOUT_MS)
  assert.equal(f.controller.signal.aborted, false)
  assert.equal(f.timers.size, 0)
}
assert.match(chatTimeoutMessage('en'), /background task may still be running/)
assert.match(chatTimeoutMessage('zh-CN'), /后台任务可能仍在运行/)
console.log('CHAT TRANSPORT WATCHDOG PASSED: silence, heartbeat, manual cancel, disposal, bilingual uncertainty')
