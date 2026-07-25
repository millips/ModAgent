import uiPress from '../assets/themes/technology-core/audio/ui-press.mp3'
import uiHover from '../assets/themes/technology-core/audio/ui-hover.mp3'
import downloadCoin from '../assets/themes/technology-core/audio/download-start-coin.mp3'
import downloadToken from '../assets/themes/technology-core/audio/download-start-token.mp3'
import downloadComplete from '../assets/themes/technology-core/audio/download-item-complete.mp3'
import installComplete from '../assets/themes/technology-core/audio/install-complete.mp3'
import snapshotComplete from '../assets/themes/technology-core/audio/snapshot-complete.mp3'
import rollback from '../assets/themes/technology-core/audio/rollback.mp3'
import warning from '../assets/themes/technology-core/audio/warning.mp3'
import errorPrimary from '../assets/themes/technology-core/audio/error-primary.mp3'
import errorSecondary from '../assets/themes/technology-core/audio/error-secondary.mp3'
import scan from '../assets/themes/technology-core/audio/scan.mp3'
import successTactile from '../assets/themes/technology-core/audio/success-tactile.mp3'
import successCoin from '../assets/themes/technology-core/audio/success-coin.mp3'
import startup from '../assets/themes/technology-core/audio/startup.mp3'
import notice from '../assets/themes/technology-core/audio/notice.mp3'
import removePrimary from '../assets/themes/technology-core/audio/remove-primary.mp3'
import removeSecondary from '../assets/themes/technology-core/audio/remove-secondary.mp3'
import cancel from '../assets/themes/technology-core/audio/cancel.mp3'
import toggle from '../assets/themes/technology-core/audio/toggle.mp3'
import catStartup1 from '../assets/themes/cat/audio/startup-1.mp3'
import catStartup2 from '../assets/themes/cat/audio/startup-2.mp3'
import catStartup3 from '../assets/themes/cat/audio/startup-3.mp3'
import catStartup4 from '../assets/themes/cat/audio/startup-4.mp3'
import catUiPress from '../assets/themes/cat/audio/ui-press.mp3'
import catUiHover from '../assets/themes/cat/audio/ui-hover.mp3'
import catDownloadStart from '../assets/themes/cat/audio/download-start.mp3'
import catDownloadComplete from '../assets/themes/cat/audio/download-complete.mp3'
import catInstallComplete from '../assets/themes/cat/audio/install-complete.mp3'
import catInstallReward from '../assets/themes/cat/audio/install-reward.mp3'
import catScanStart from '../assets/themes/cat/audio/scan-start.mp3'
import catScanComplete from '../assets/themes/cat/audio/scan-complete.mp3'
import catScanFinish from '../assets/themes/cat/audio/scan-finish.mp3'
import catNotice from '../assets/themes/cat/audio/notice.mp3'
import catRemove from '../assets/themes/cat/audio/remove.mp3'
import catCancel from '../assets/themes/cat/audio/cancel.mp3'
import catRollback from '../assets/themes/cat/audio/rollback.mp3'
import catToggleOn from '../assets/themes/cat/audio/toggle-on.mp3'
import catToggleOff from '../assets/themes/cat/audio/toggle-off.mp3'
import catWarning from '../assets/themes/cat/audio/warning.mp3'
import catError from '../assets/themes/cat/audio/error.mp3'
import catBatchComplete from '../assets/themes/cat/audio/batch-complete.mp3'
import catEasterMeowSoft from '../assets/themes/cat/audio/easter-meow-soft.mp3'
import catEasterMeowNatural from '../assets/themes/cat/audio/easter-meow-natural.mp3'
import catEasterPurr from '../assets/themes/cat/audio/easter-purr.mp3'

const CORE_SOUND_MAP = {
  startup: [{ src: startup, gain: 1 }],
  manual: [{ src: uiPress, gain: .5 }],
  press: [{ src: uiPress, gain: .5 }],
  hover: [{ src: uiHover, gain: .5 }],
  'download-start': [
    { src: downloadCoin, gain: 1 },
    { src: downloadToken, gain: 1 },
  ],
  'download-item-complete': [{ src: downloadComplete, gain: 1 }],
  'download-batch-complete': [
    { src: successTactile, gain: .82 },
    { src: successCoin, gain: .48, delay: 150 },
  ],
  'install-start': [{ src: installComplete, gain: 1 }],
  'install-complete': [
    { src: successTactile, gain: .82 },
    { src: successCoin, gain: .48, delay: 150 },
  ],
  'snapshot-complete': [{ src: snapshotComplete, gain: 1 }],
  'rollback-complete': [{ src: rollback, gain: 1 }],
  'remove-complete': [
    { src: removePrimary, gain: .72 },
    { src: removeSecondary, gain: .5, delay: 110 },
  ],
  success: [
    { src: successTactile, gain: .82 },
    { src: successCoin, gain: .48, delay: 150 },
  ],
  notice: [{ src: notice, gain: .75 }],
  'reply-complete': [{ src: notice, gain: .32, rate: 1.08 }],
  cancel: [{ src: cancel, gain: 1, duration: .45 }],
  enable: [{ src: toggle, gain: 2 }],
  disable: [{ src: toggle, gain: 2 }],
  'scan-start': [{ src: scan, gain: 1 }],
  'scan-complete': [{ src: notice, gain: .75 }],
  warning: [{ src: warning, gain: .25 }],
  // Confirmed Feedback Lab safety setting: 1.4x speed, 0.2 volume.
  destructive: [{ src: warning, gain: .2, rate: 1.4 }],
  error: [
    { src: errorPrimary, gain: .44 },
    { src: errorSecondary, gain: .31, delay: 90 },
  ],
}

const CAT_SOUND_MAP = {
  // The four source files are consecutive notes. Startup uses gapless
  // sequential playback below rather than fixed-delay overlap.
  startup: [
    { src: catStartup1, gain: .78 },
    { src: catStartup2, gain: .78 },
    { src: catStartup3, gain: .78 },
    { src: catStartup4, gain: .78 },
  ],
  manual: [{ src: catUiPress, gain: .58 }],
  press: [{ src: catUiPress, gain: .58 }],
  hover: [{ src: catUiHover, gain: .08 }],
  'download-start': [{ src: catDownloadStart, gain: .82 }],
  'download-item-complete': [{ src: catDownloadComplete, gain: .86 }],
  'download-batch-complete': [{ src: catBatchComplete, gain: .82 }],
  'install-start': [{ src: catUiPress, gain: .4, rate: .92 }],
  'install-complete': [
    { src: catInstallComplete, gain: .84 },
    { src: catInstallReward, gain: .6, delay: 125 },
  ],
  'install-batch-complete': [{ src: catBatchComplete, gain: .86 }],
  'snapshot-complete': [{ src: catNotice, gain: .72 }],
  'rollback-complete': [{ src: catRollback, gain: .76 }],
  'remove-complete': [{ src: catRemove, gain: .72 }],
  success: [
    { src: catInstallComplete, gain: .78 },
    { src: catInstallReward, gain: .54, delay: 125 },
  ],
  notice: [{ src: catNotice, gain: .68 }],
  'reply-complete': [{ src: catNotice, gain: .38 }],
  cancel: [{ src: catCancel, gain: .72 }],
  enable: [{ src: catToggleOn, gain: .66 }],
  disable: [{ src: catToggleOff, gain: .66 }],
  'scan-start': [{ src: catScanStart, gain: .58 }],
  'scan-complete': [
    { src: catScanComplete, gain: .68 },
    { src: catScanFinish, gain: .42, delay: 105 },
  ],
  warning: [{ src: catWarning, gain: .42 }],
  destructive: [{ src: catWarning, gain: .34, rate: 1.12 }],
  error: [{ src: catError, gain: .52, duration: .5 }],
}

const CAT_EASTER_SOUNDS = [catEasterMeowSoft, catEasterMeowNatural, catEasterPurr]

const active = new Set()
let installBufferPromise = null
let audioContext = null
const SOUND_VOLUME_KEY = 'modagent-feedback-sound-volumes'

function masterVolume() {
  try {
    const saved = localStorage.getItem('modagent-feedback-volume')
    // Number(null) and Number('') are both 0. Treat an absent/blank setting as
    // "not configured" so first-run users hear the intended default volume.
    if (saved === null || saved.trim() === '') return .72
    const value = Number(saved)
    return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : .72
  } catch (_) {
    return .72
  }
}

function readSoundVolumes() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SOUND_VOLUME_KEY) || '{}')
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch (_) {
    return {}
  }
}

export function getFeedbackSoundVolume(type) {
  const value = Number(readSoundVolumes()[type])
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1
}

export function setFeedbackSoundVolume(type, value) {
  const volumes = readSoundVolumes()
  volumes[type] = Math.max(0, Math.min(1, Number(value) || 0))
  try { localStorage.setItem(SOUND_VOLUME_KEY, JSON.stringify(volumes)) } catch (_) {}
  return volumes[type]
}

export function resetFeedbackSoundVolumes() {
  try { localStorage.removeItem(SOUND_VOLUME_KEY) } catch (_) {}
}

function playLayer(layer, extraDelay = 0, soundVolume = 1, waitForEnd = false) {
  return new Promise(resolve => {
    window.setTimeout(async () => {
      const audio = new Audio(layer.src)
      let boostedNodes = null
      if (layer.gain > 1 && (window.AudioContext || window.webkitAudioContext)) {
        try {
          if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)()
          if (audioContext.state === 'suspended') await audioContext.resume()
          const source = audioContext.createMediaElementSource(audio)
          const gain = audioContext.createGain()
          gain.gain.value = layer.gain * masterVolume() * soundVolume
          source.connect(gain).connect(audioContext.destination)
          audio.volume = 1
          boostedNodes = { source, gain }
        } catch (_) {
          audio.volume = Math.max(0, Math.min(1, layer.gain * masterVolume() * soundVolume))
        }
      } else {
        audio.volume = Math.max(0, Math.min(1, layer.gain * masterVolume() * soundVolume))
      }
      audio.playbackRate = layer.rate || 1
      audio.preload = 'auto'
      active.add(audio)
      let durationTimer = null
      let settled = false
      const settle = value => {
        if (settled) return
        settled = true
        resolve(value)
      }
      const release = () => {
        if (durationTimer) {
          window.clearTimeout(durationTimer)
          durationTimer = null
        }
        if (boostedNodes) {
          try { boostedNodes.source.disconnect(); boostedNodes.gain.disconnect() } catch (_) {}
          boostedNodes = null
        }
        active.delete(audio)
      }
      audio.addEventListener('ended', () => { release(); settle(true) }, { once: true })
      audio.addEventListener('error', () => { release(); settle(false) }, { once: true })
      audio.play().then(() => {
        if (layer.duration) {
          durationTimer = window.setTimeout(() => {
            audio.pause()
            release()
            settle(true)
          }, layer.duration * 1000 / audio.playbackRate)
        }
        if (!waitForEnd) settle(true)
      }).catch(error => {
        console.warn('[feedback-audio] playback failed', error)
        release()
        settle(false)
      })
    }, extraDelay + (layer.delay || 0))
  })
}

function playLayers(layers, extraDelay = 0, soundVolume = 1) {
  return Promise.all(layers.map(layer => playLayer(layer, extraDelay, soundVolume)))
    .then(results => results.some(Boolean))
}

async function playSequence(layers, soundVolume = 1) {
  let played = false
  for (const layer of layers) {
    // Waiting for `ended` prevents drift and hands the next startup note over
    // immediately, which keeps the four-note phrase compact and in order.
    played = await playLayer(layer, 0, soundVolume, true) || played
  }
  return played
}

async function getInstallBuffer() {
  if (!window.AudioContext && !window.webkitAudioContext) return null
  if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)()
  if (audioContext.state === 'suspended') await audioContext.resume()
  if (!installBufferPromise) {
    installBufferPromise = fetch(installComplete)
      .then(response => response.arrayBuffer())
      .then(bytes => audioContext.decodeAudioData(bytes))
      .catch(() => null)
  }
  return installBufferPromise
}

function strongestWindow(buffer, seconds = .14) {
  const data = buffer.getChannelData(0)
  const size = Math.max(1, Math.floor(seconds * buffer.sampleRate))
  const step = Math.max(1, Math.floor(size / 8))
  let best = 0
  let bestEnergy = -1
  for (let i = 0; i + size < data.length; i += step) {
    let energy = 0
    for (let j = i; j < i + size; j += 8) energy += data[j] * data[j]
    if (energy > bestEnergy) { bestEnergy = energy; best = i }
  }
  return { offset: best / buffer.sampleRate, duration: Math.min(seconds, buffer.duration - best / buffer.sampleRate) }
}

async function playInstallBatch(detail = {}) {
  const count = Math.max(1, Math.min(30, Number(detail.count) || 1))
  const soundVolume = getFeedbackSoundVolume('install-batch-complete')
  const buffer = await getInstallBuffer()
  let elapsed = 0

  if (buffer && audioContext) {
    const cut = strongestWindow(buffer)
    for (let i = 0; i < count; i++) {
      const progress = count === 1 ? 1 : i / (count - 1)
      const source = audioContext.createBufferSource()
      const gain = audioContext.createGain()
      source.buffer = buffer
      source.playbackRate.value = 1
      gain.gain.value = Math.max(.42, .82 - Math.max(0, count - 6) * .012) * masterVolume() * soundVolume
      source.connect(gain).connect(audioContext.destination)
      source.start(audioContext.currentTime + elapsed / 1000, cut.offset, cut.duration)
      elapsed += 130 - progress * 65
    }
  } else {
    for (let i = 0; i < count; i++) {
      const progress = count === 1 ? 1 : i / (count - 1)
      playLayer({ src: installComplete, gain: Math.max(.3, .72 - count * .01) }, elapsed, soundVolume)
      elapsed += 130 - progress * 65
    }
  }
  playLayers(CORE_SOUND_MAP.success, elapsed + 170, soundVolume)
  return true
}

export function playFeedbackSound(type, detail = {}) {
  if (typeof window === 'undefined') return Promise.resolve(false)
  const catTheme = document.body?.dataset?.maTheme === 'cat'
  const soundVolume = getFeedbackSoundVolume(type)
  if (catTheme) {
    if (type === 'startup') return playSequence(CAT_SOUND_MAP.startup, soundVolume)
    if (type === 'manual' && detail.source === 'feedback-core-manual' && Math.random() < .05) {
      const src = CAT_EASTER_SOUNDS[Math.floor(Math.random() * CAT_EASTER_SOUNDS.length)]
      return playLayers([{ src, gain: .34 }], 0, soundVolume)
    }
    return playLayers(CAT_SOUND_MAP[type] || [], 0, soundVolume)
  }
  if (type === 'install-batch-complete') return playInstallBatch(detail)
  return playLayers(CORE_SOUND_MAP[type] || [], 0, soundVolume)
}
