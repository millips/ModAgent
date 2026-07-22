import { FEEDBACK_EVENT, emitFeedback } from './feedbackBus'
import { playFeedbackSound } from './feedbackAudio'

let installed = false
let startupPlayed = false
let startupPromise = null
let lastHoverAt = 0

const CONTROL_SELECTOR = 'button, [role="button"], select, input[type="checkbox"], input[type="radio"]'

function controlFrom(target) {
  const control = target instanceof Element ? target.closest(CONTROL_SELECTOR) : null
  if (!control || control.disabled || control.getAttribute('aria-disabled') === 'true') return null
  return control
}

function isCancel(control) {
  const intent = control.dataset.feedback
  const label = `${control.textContent || ''} ${control.getAttribute('title') || ''}`.trim()
  return intent === 'cancel' || /取消|关闭/.test(label)
}

function isDestructive(control) {
  return control.dataset.feedback === 'destructive' ||
    control.classList.contains('btn-danger') ||
    control.classList.contains('tc-danger-button')
}

async function retryStartup() {
  if (startupPlayed) return
  if (!startupPromise) {
    startupPromise = playFeedbackSound('startup')
      .then(ok => {
        if (ok) startupPlayed = true
        return ok
      })
      .finally(() => { startupPromise = null })
  }
  await startupPromise
}

export function installFeedbackInteractions() {
  if (installed || typeof document === 'undefined') return
  installed = true

  window.addEventListener(FEEDBACK_EVENT, event => {
    const type = event.detail?.type
    if (!type) return
    if (type === 'startup') retryStartup()
    else playFeedbackSound(type, event.detail)
  })

  document.addEventListener('pointerover', event => {
    const control = controlFrom(event.target)
    if (!control || control.contains(event.relatedTarget)) return
    const now = Date.now()
    if (now - lastHoverAt < 90) return
    lastHoverAt = now
    playFeedbackSound('hover')
  }, true)

  document.addEventListener('pointerdown', event => {
    const control = controlFrom(event.target)
    if (!control || event.button !== 0) return
    if (!startupPlayed) retryStartup()
    if (isDestructive(control)) emitFeedback('destructive', { source: 'control' })
    else if (isCancel(control)) emitFeedback('cancel', { source: 'control' })
    else if (!control.classList.contains('feedback-core-button') && control.dataset.feedbackNoPress !== 'true') {
      playFeedbackSound('press')
    }
  }, true)

  // Electron normally permits startup audio. If Chromium blocks autoplay, the
  // first user gesture above retries it without replaying the startup visual.
  window.setTimeout(() => emitFeedback('startup', { source: 'app' }), 320)
}
