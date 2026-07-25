import React, { useEffect, useRef, useState } from 'react'
import coreShell from '../assets/themes/technology-core/core/core-shell.png'
import minimalTechCoreShell from '../assets/themes/minimal-tech/core/core-sphere-plaster-02.png'
import kawaiiCoreShell from '../assets/themes/kawaii/core/core-shell.png'
import kawaiiCoreSphere from '../assets/themes/kawaii/core/core-sphere.png'
import gothicRoseWindow from '../assets/themes/gothic/core/rose-window-core-v1.png'
import tacticalOpticCore from '../assets/themes/tactical/core/optic-core-v1.png'
import abyssalAstrolabeEye from '../assets/themes/abyssal/core/astrolabe-eye-v1.png'
import { FEEDBACK_EVENT, emitFeedback } from '../feedback/feedbackBus'

const PAGE_META = {
  chat: { label: 'DIALOG CORE', tone: 'chat' },
  mods: { label: 'MOD MATRIX', tone: 'mods' },
  snaps: { label: 'SNAPSHOT CORE', tone: 'snaps' },
  settings: { label: 'SYSTEM CORE', tone: 'settings' },
}

const EFFECT_META = {
  startup: { css: 'fx-startup', label: 'SYSTEM ONLINE', duration: 1200 },
  manual: { css: 'fx-manual', label: 'PULSE', duration: 650 },
  'download-start': { css: 'fx-download-start', label: 'ACQUIRE', duration: 1050 },
  'download-item-complete': { css: 'fx-success', label: 'RECEIVED', duration: 900 },
  'download-batch-complete': { css: 'fx-batch', label: 'BATCH COMMIT', duration: 1250 },
  'install-start': { css: 'fx-install', label: 'MODULE INSERT', duration: 1150 },
  'install-complete': { css: 'fx-success', label: 'READY', duration: 900 },
  'install-batch-complete': { css: 'fx-batch', label: 'INSTALL COMMIT', duration: 1350 },
  'snapshot-complete': { css: 'fx-snapshot', label: 'STATE SEALED', duration: 1350 },
  'rollback-complete': { css: 'fx-rollback', label: 'REWIND', duration: 900 },
  'remove-complete': { css: 'fx-remove', label: 'REMOVED', duration: 900 },
  'scan-start': { css: 'fx-scan', label: 'SCANNING', duration: 1300 },
  'scan-complete': { css: 'fx-success', label: 'SCAN CLEAR', duration: 900 },
  success: { css: 'fx-success', label: 'CONFIRMED', duration: 900 },
  notice: { css: 'fx-notice', label: 'NOTICE', duration: 800 },
  cancel: { css: 'fx-cancel', label: 'CANCELLED', duration: 800 },
  enable: { css: 'fx-enable', label: 'ONLINE', duration: 850 },
  disable: { css: 'fx-disable', label: 'OFFLINE', duration: 850 },
  destructive: { css: 'fx-warning', label: 'HOLD CAUTION', duration: 1100 },
  warning: { css: 'fx-warning', label: 'CAUTION', duration: 1100 },
  error: { css: 'fx-error', label: 'FAILED', duration: 900 },
}

const COMBO_ELIGIBLE = new Set([
  'download-start', 'download-item-complete', 'download-batch-complete',
  'install-complete', 'install-batch-complete', 'remove-complete',
  'snapshot-complete', 'rollback-complete', 'enable', 'disable',
  'scan-start', 'scan-complete', 'success',
])
const COMBO_RESET = new Set(['error', 'warning', 'destructive', 'cancel'])

const PARTICLE_PALETTES = {
  'download-start': ['#ffd95c', '#ff9d28', '#fff4bd'],
  'download-batch-complete': ['#ffd95c', '#79f7ff', '#ffffff'],
  'install-start': ['#57f4ff', '#8f7cff', '#d8ffff'],
  'install-complete': ['#57f4ff', '#ffd95c', '#ffffff'],
  'install-batch-complete': ['#ffd95c', '#57f4ff', '#8f7cff'],
  'snapshot-complete': ['#b06cff', '#72eaff', '#ffffff'],
  'rollback-complete': ['#b06cff', '#45d9ff', '#ffffff'],
  enable: ['#6dffc2', '#62efff', '#ffffff'],
  disable: ['#748093', '#9aa8ba', '#d8e0e9'],
  cancel: ['#a58cff', '#6f7cff', '#ffffff'],
  warning: ['#ff355f', '#ffb02e', '#fff2cf'],
  destructive: ['#ff355f', '#ffb02e', '#fff2cf'],
  error: ['#ff355f', '#ff7b55', '#ffffff'],
}

const KAWAII_PARTICLE_PALETTES = {
  warning: ['#ff6f91', '#ffd27a', '#fff5dd'],
  destructive: ['#ff557d', '#ffae78', '#fff2e7'],
  error: ['#ff557d', '#ff8f9f', '#ffffff'],
  disable: ['#b7a6b7', '#d5c5d6', '#f7edf5'],
  cancel: ['#cbb6ff', '#ffb7cf', '#ffffff'],
  default: ['#ffb7cf', '#cbb6ff', '#ffe1a8', '#ffffff'],
}

const CAT_PARTICLE_PALETTES = {
  warning: ['#e5b96e', '#d97966', '#fff0bd'],
  destructive: ['#d96b60', '#e5b96e', '#fff0bd'],
  error: ['#d96b60', '#f09a80', '#f8ead2'],
  disable: ['#72848d', '#9aabb2', '#d7e1df'],
  cancel: ['#9b9bd7', '#9bd7de', '#f2d99b'],
  default: ['#9bd7de', '#d6b66f', '#f2d99b', '#f5f1e7'],
}

const GOTHIC_PARTICLE_PALETTES = {
  warning: ['#b58a55', '#8f2438', '#e5c59e'],
  destructive: ['#9f1f36', '#c65b45', '#ded0bc'],
  error: ['#a61f3a', '#d05a6e', '#d8c8be'],
  disable: ['#56606d', '#7f8995', '#b6bdc5'],
  cancel: ['#75578f', '#9a3150', '#c6b1cf'],
  default: ['#b9c4d0', '#8f2438', '#75578f', '#d9c7a4'],
}

const TACTICAL_PARTICLE_PALETTES = {
  warning: ['#d39238', '#b34832', '#e6c38b'],
  destructive: ['#d13d2f', '#e27835', '#f1c37f'],
  error: ['#d13d2f', '#ff6a4c', '#c9b493'],
  disable: ['#57605c', '#7c847d', '#a3a99f'],
  cancel: ['#88765a', '#6f7962', '#c3ad82'],
  default: ['#c49a5a', '#78866b', '#d39238', '#d9d3c7'],
}

const ABYSSAL_PARTICLE_PALETTES = {
  warning: ['#b78c4f', '#65529a', '#a9d9d4'],
  destructive: ['#8c385e', '#7551a3', '#d0b780'],
  error: ['#973b68', '#8d5ab5', '#bfded8'],
  disable: ['#435c5d', '#647879', '#98aaa7'],
  cancel: ['#5f568e', '#3d7778', '#b6a37b'],
  default: ['#5ca8a6', '#b78c4f', '#7350a0', '#c6e0dc'],
}

function makeParticles(type, comboCount = 0, peak = false) {
  const base = type.includes('batch') ? 24 : type === 'snapshot-complete' ? 10 : 16
  const count = Math.min(peak ? 40 : 30, Math.ceil(base * (1 + Math.min(comboCount, 6) * .1)))
  const visualTheme = document.body.dataset.maTheme
  const palette = visualTheme === 'kawaii'
    ? (KAWAII_PARTICLE_PALETTES[type] || KAWAII_PARTICLE_PALETTES.default)
    : visualTheme === 'cat'
      ? (CAT_PARTICLE_PALETTES[type] || CAT_PARTICLE_PALETTES.default)
      : visualTheme === 'gothic'
        ? (GOTHIC_PARTICLE_PALETTES[type] || GOTHIC_PARTICLE_PALETTES.default)
        : visualTheme === 'tactical'
          ? (TACTICAL_PARTICLE_PALETTES[type] || TACTICAL_PARTICLE_PALETTES.default)
          : visualTheme === 'abyssal'
            ? (ABYSSAL_PARTICLE_PALETTES[type] || ABYSSAL_PARTICLE_PALETTES.default)
      : (PARTICLE_PALETTES[type] || ['#57f4ff', '#8f7cff', '#d8ffff'])
  return Array.from({ length: count }, (_, i) => {
    const angle = Math.random() * Math.PI * 2
    const distance = 55 + Math.random() * (70 + Math.min(comboCount, 6) * 6)
    return {
      id: `${Date.now()}-${i}`,
      x: Math.cos(angle) * distance,
      y: Math.sin(angle) * distance,
      size: 4 + Math.random() * 5 + (peak ? 2 : Math.min(comboCount, 5) * .25),
      color: palette[i % palette.length],
      duration: 420 + Math.random() * 340,
    }
  })
}

function makeResultShape() {
  const radius = () => {
    const values = Array.from({ length: 8 }, () => 40 + Math.round(Math.random() * 24))
    return `${values.slice(0, 4).join('% ')}% / ${values.slice(4).join('% ')}%`
  }
  const x = Math.random() * 18 - 9
  const y = Math.random() * 14 - 7
  return {
    '--shape-a': radius(), '--shape-b': radius(), '--shape-c': radius(),
    '--shape-x': `${x.toFixed(1)}px`, '--shape-y': `${y.toFixed(1)}px`,
    '--shape-rot': `${(Math.random() * 44 - 22).toFixed(1)}deg`,
  }
}

export default function FeedbackCore({ page }) {
  const pageMeta = PAGE_META[page] || PAGE_META.chat
  const [run, setRun] = useState(null)
  const clearTimer = useRef(null)
  const restartFrame = useRef(null)
  const comboTimer = useRef(null)
  const comboCount = useRef(0)
  const lastComboAt = useRef(0)
  const [combo, setCombo] = useState(null)

  useEffect(() => {
    const handle = event => {
      if (!document.body.classList.contains('theme-technology-core')) return
      const type = event.detail?.type
      const meta = EFFECT_META[type]
      if (!meta) return

      let chain = 0
      let peak = false
      if (COMBO_RESET.has(type)) {
        comboCount.current = 0
        setCombo(null)
      } else if (COMBO_ELIGIBLE.has(type)) {
        const now = Date.now()
        comboCount.current = now - lastComboAt.current < 1250 ? comboCount.current + 1 : 1
        lastComboAt.current = now
        chain = comboCount.current
        peak = chain === 3 || chain === 5 || chain === 10 || (chain > 10 && chain % 5 === 0)
        setCombo({ count: chain, peak })
        window.clearTimeout(comboTimer.current)
        comboTimer.current = window.setTimeout(() => {
          comboCount.current = 0
          setCombo(null)
        }, 1550)
      }

      window.clearTimeout(clearTimer.current)
      window.cancelAnimationFrame(restartFrame.current)
      setRun(null)
      restartFrame.current = window.requestAnimationFrame(() => {
        setRun({
          id: `${Date.now()}-${Math.random()}`, type, ...meta,
          particles: makeParticles(type, chain, peak), resultShape: makeResultShape(),
        })
        clearTimer.current = window.setTimeout(() => setRun(null), meta.duration)
      })
    }
    window.addEventListener(FEEDBACK_EVENT, handle)
    return () => {
      window.removeEventListener(FEEDBACK_EVENT, handle)
      window.clearTimeout(clearTimer.current)
      window.clearTimeout(comboTimer.current)
      window.cancelAnimationFrame(restartFrame.current)
    }
  }, [])

  const manualPulse = () => emitFeedback('manual', { page, source: 'feedback-core-manual' })

  return (
    <section className={`feedback-core-station tone-${pageMeta.tone} ${run?.css || ''}`} aria-label="反馈核心">
      <button className="feedback-core-button" onClick={manualPulse}
        aria-label="反馈核心" title="点击测试科技核心反馈">
        <span className="feedback-core-cat-ears" aria-hidden="true"><i /><i /></span>
        <span className="feedback-core-cat-whiskers" aria-hidden="true"><i /><i /><i /><i /></span>
        <span className="feedback-core-cat-moon" aria-hidden="true">☾</span>
        <span className="feedback-core-field" />
        <span className="feedback-core-orbit orbit-outer" />
        <span className="feedback-core-orbit orbit-inner" />
        <img src={kawaiiCoreSphere} className="feedback-core-kawaii-sphere" alt="" draggable="false" />
        <img src={coreShell} className="feedback-core-art feedback-core-art-technology" alt="" draggable="false" />
        <img src={minimalTechCoreShell} className="feedback-core-art feedback-core-art-minimal" alt="" draggable="false" />
        <img src={kawaiiCoreShell} className="feedback-core-art feedback-core-art-kawaii" alt="" draggable="false" />
        <img src={gothicRoseWindow} className="feedback-core-art feedback-core-art-gothic" alt="" draggable="false" />
        <img src={tacticalOpticCore} className="feedback-core-art feedback-core-art-tactical" alt="" draggable="false" />
        <img src={abyssalAstrolabeEye} className="feedback-core-art feedback-core-art-abyssal" alt="" draggable="false" />
        <span className="feedback-core-lens" />
        <span className="feedback-core-result" style={run?.resultShape} />
        <span className="feedback-core-membrane" />
        <span className="feedback-core-module">DATA<i /></span>
        <span className="feedback-core-lanes"><i /><i /><i /></span>
        {run && <span key={run.id} className="feedback-core-particles">
          {run.particles.map(p => <i key={p.id} style={{
            '--x': `${p.x}px`, '--y': `${p.y}px`, '--size': `${p.size}px`,
            '--color': p.color, '--dur': `${p.duration}ms`,
          }} />)}
        </span>}
        {combo && <span className={`feedback-core-combo ${combo.peak ? 'is-peak' : ''}`}>
          <b>×{combo.count}</b><small>CHAIN</small><i /><i /><i />
        </span>}
      </button>
      <div className="feedback-core-caption">
        <span>{run?.label || pageMeta.label}</span>
        <small>{run ? 'EVENT RESPONSE' : 'PRESS TO TEST'}</small>
      </div>
    </section>
  )
}
