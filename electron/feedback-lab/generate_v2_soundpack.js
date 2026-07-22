const fs = require('fs')
const path = require('path')
const os = require('os')

const SR = 48000
const TAU = Math.PI * 2
const outDir = path.join(os.homedir(), 'Desktop', '音频素材', 'ModAgent_V2')
fs.mkdirSync(outDir, { recursive: true })

function rng(seed) {
  let value = seed >>> 0
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0
    return value / 4294967296
  }
}

function env(t, attack, decay, sustain = 0, releaseAt = 9, release = .1) {
  const a = Math.min(1, t / Math.max(.0001, attack))
  const d = sustain + (1 - sustain) * Math.exp(-Math.max(0, t - attack) / Math.max(.0001, decay))
  const r = t < releaseAt ? 1 : Math.exp(-(t - releaseAt) / Math.max(.0001, release))
  return a * d * r
}

function sine(t, hz, phase = 0) { return Math.sin(TAU * hz * t + phase) }
function tri(t, hz) { return 2 / Math.PI * Math.asin(Math.sin(TAU * hz * t)) }
function soft(x, drive = 1.4) { return Math.tanh(x * drive) / Math.tanh(drive) }
function pan(value, position) {
  const angle = (position + 1) * Math.PI / 4
  return [value * Math.cos(angle), value * Math.sin(angle)]
}

function render(name, duration, seed, synth, options = {}) {
  const count = Math.ceil(duration * SR)
  const left = new Float64Array(count)
  const right = new Float64Array(count)
  const random = rng(seed)

  for (let i = 0; i < count; i++) {
    const t = i / SR
    const sample = synth(t, random, i)
    if (Array.isArray(sample)) {
      left[i] += sample[0]
      right[i] += sample[1]
    } else {
      left[i] += sample
      right[i] += sample
    }
  }

  for (const tap of options.echoes || []) {
    const delay = Math.floor(tap.delay * SR)
    for (let i = delay; i < count; i++) {
      left[i] += right[i - delay] * tap.gain
      right[i] += left[i - delay] * tap.gain * .93
    }
  }

  let peak = 0
  for (let i = 0; i < count; i++) peak = Math.max(peak, Math.abs(left[i]), Math.abs(right[i]))
  const scale = (options.peak || .88) / Math.max(.0001, peak)
  const pcm = Buffer.alloc(count * 4)
  for (let i = 0; i < count; i++) {
    const fade = i < 32 ? i / 32 : i > count - 96 ? (count - i) / 96 : 1
    pcm.writeInt16LE(Math.round(Math.max(-1, Math.min(1, left[i] * scale * fade)) * 32767), i * 4)
    pcm.writeInt16LE(Math.round(Math.max(-1, Math.min(1, right[i] * scale * fade)) * 32767), i * 4 + 2)
  }

  const header = Buffer.alloc(44)
  header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVE', 8)
  header.write('fmt ', 12); header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20)
  header.writeUInt16LE(2, 22); header.writeUInt32LE(SR, 24); header.writeUInt32LE(SR * 4, 28)
  header.writeUInt16LE(4, 32); header.writeUInt16LE(16, 34); header.write('data', 36)
  header.writeUInt32LE(pcm.length, 40)
  fs.writeFileSync(path.join(outDir, `V2_${name}.wav`), Buffer.concat([header, pcm]))
}

const noiseBurst = (t, random, decay = 45) => (random() * 2 - 1) * Math.exp(-t * decay)
const click = (t, random, hz = 1600) =>
  noiseBurst(t, random, 95) * .65 + sine(t, hz + 900 * Math.exp(-t * 70)) * Math.exp(-t * 52) * .38

render('startup', 1.12, 101, (t, r) => {
  const rise = Math.min(1, t / .42)
  const low = sine(t, 48 + rise * 28) * env(t, .035, .8, .18, .88, .16) * .42
  const shimmer = sine(t, 720 + 980 * rise * rise) * env(t, .14, .38, 0, .75, .18) * .14
  const sweep = (r() * 2 - 1) * env(t, .08, .34, 0, .62, .2) * .1
  return pan(soft(low + shimmer + sweep), Math.sin(t * 5) * .24)
}, { echoes: [{ delay: .087, gain: .18 }, { delay: .173, gain: .1 }] })

render('hover', .18, 102, (t, r) =>
  pan(click(t, r, 2100) * .35 + sine(t, 510) * env(t, .003, .055) * .2, .18))

render('press', .26, 103, (t, r) => {
  const mechanical = click(t, r, 1250) * .46
  const body = sine(t, 92 + 34 * Math.exp(-t * 24)) * env(t, .004, .11) * .58
  return pan(soft(mechanical + body, 1.7), -.08)
})

render('download_start_coin', .52, 104, (t, r) => {
  const hit = click(t, r, 2450) * .38
  const ring = [1480, 1977, 2680].reduce((v, hz, i) => v + sine(t, hz) * Math.exp(-t * (10 + i * 3)) * (.28 - i * .05), 0)
  return pan(hit + ring, -.32 + t * 1.1)
}, { echoes: [{ delay: .042, gain: .16 }] })

render('download_start_token', .48, 105, (t, r) => {
  const mech = click(t, r, 880) * .5
  const motor = tri(t, 118 - 24 * t) * env(t, .006, .16) * .25
  const lock = t > .105 ? sine(t - .105, 1840) * Math.exp(-(t - .105) * 35) * .3 : 0
  return pan(soft(mech + motor + lock), .28)
})

render('download_complete', .62, 106, (t, r) => {
  const transient = click(t, r, 1750) * .32
  const chord = [330, 495, 660].reduce((v, hz, i) => v + sine(t, hz) * env(t, .004 + i * .012, .23) * (.24 - i * .03), 0)
  return pan(transient + chord, Math.sin(t * 8) * .18)
}, { echoes: [{ delay: .075, gain: .16 }] })

render('install', .44, 107, (t, r) => {
  const insert = click(t, r, 720) * .62
  const rail = noiseBurst(t, r, 22) * .16
  const latchT = t - .115
  const latch = latchT > 0 ? click(latchT, r, 1850) * .52 : 0
  const body = sine(t, 74) * env(t, .003, .14) * .45
  return pan(soft(insert + rail + latch + body, 1.8), -.12)
})

render('success_tactile', .34, 108, (t, r) => {
  const snap = click(t, r, 2050) * .5
  const body = sine(t, 118) * env(t, .002, .1) * .55
  const shine = sine(t, 920) * env(t, .008, .13) * .18
  return pan(soft(snap + body + shine), .06)
})

render('success_coin', .5, 109, (t, r) => {
  const hit = click(t, r, 2800) * .3
  const ring = sine(t, 1760) * Math.exp(-t * 10) * .42 + sine(t, 2636) * Math.exp(-t * 14) * .2
  return pan(hit + ring, .3)
}, { echoes: [{ delay: .054, gain: .13 }] })

render('notice', .48, 110, (t) => {
  const tone = sine(t, 690) * env(t, .01, .2) * .38 + sine(t, 1035) * env(t, .035, .16) * .2
  return pan(tone, -.1 + t * .4)
}, { echoes: [{ delay: .09, gain: .14 }] })

render('remove_primary', .46, 111, (t, r) => {
  const release = click(t, r, 680) * .56
  const reverse = noiseBurst(t, r, 9) * Math.min(1, t / .08) * Math.exp(-t * 5) * .16
  const drop = sine(t, 105 - 44 * Math.min(1, t / .3)) * env(t, .004, .2) * .42
  return pan(soft(release + reverse + drop), -.18)
})

render('remove_secondary', .55, 112, (t, r) => {
  const down = sine(t, 170 - 105 * Math.min(1, t / .36)) * env(t, .004, .28) * .46
  const debris = noiseBurst(t, r, 18) * .12
  return pan(soft(down + debris), .2)
}, { echoes: [{ delay: .064, gain: .12 }] })

render('snapshot', .92, 113, (t, r) => {
  const stretch = sine(t, 82 + 20 * Math.sin(t * 9)) * env(t, .09, .55, .1, .68, .18) * .32
  const membrane = noiseBurst(t, r, 5) * Math.sin(Math.PI * Math.min(1, t / .55)) * .18
  const sealT = t - .5
  const seal = sealT > 0 ? click(sealT, r, 980) * .46 + sine(sealT, 58) * Math.exp(-sealT * 8) * .42 : 0
  return pan(soft(stretch + membrane + seal), Math.sin(t * 4) * .22)
}, { echoes: [{ delay: .11, gain: .14 }] })

render('rollback', .94, 114, (t, r) => {
  const phase = Math.min(1, t / .42)
  const rewind = sine(t, 240 + 900 * phase * phase) * env(t, .025, .42, 0, .43, .12) * .27
  const tension = sine(t, 66 + 18 * phase) * env(t, .02, .4, .12, .43, .12) * .38
  const releaseT = t - .43
  const reverse = releaseT > 0 ? sine(releaseT, 1140 - 920 * Math.min(1, releaseT / .42)) * Math.exp(-releaseT * 4.5) * .3 : 0
  const air = noiseBurst(t, r, 3.8) * env(t, .04, .52, 0, .78, .12) * .09
  return pan(soft(rewind + tension + reverse + air), Math.sin(t * 10) * .38)
}, { echoes: [{ delay: .068, gain: .2 }, { delay: .136, gain: .1 }] })

render('warning', .82, 115, (t, r) => {
  const pulse = (offset) => {
    const x = t - offset
    return x > 0 ? (sine(x, 94) * .5 + sine(x, 188) * .2 + noiseBurst(x, r, 35) * .12) * env(x, .005, .16) : 0
  }
  return pan(soft(pulse(0) + pulse(.29)), 0)
}, { echoes: [{ delay: .047, gain: .1 }] })

render('error_primary', .52, 116, (t, r) => {
  const fracture = click(t, r, 520) * .58
  const fall = sine(t, 146 - 82 * Math.min(1, t / .34)) * env(t, .003, .24) * .58
  return pan(soft(fracture + fall, 2), -.22)
})

render('error_secondary', .48, 117, (t, r) => {
  const buzz = tri(t, 62) * env(t, .006, .22) * .34
  const staticHit = noiseBurst(t, r, 18) * .18
  return pan(soft(buzz + staticHit), .24)
})

render('cancel', .42, 118, (t, r) => {
  const stop = click(t, r, 1050) * .45
  const fold = sine(t, 310 - 210 * Math.min(1, t / .28)) * env(t, .003, .2) * .4
  return pan(soft(stop + fold), -.08)
})

render('toggle', .3, 119, (t, r) => {
  const snap = click(t, r, 1550) * .58
  const relay = sine(t, 132) * env(t, .002, .09) * .48
  const contactT = t - .065
  const contact = contactT > 0 ? sine(contactT, 2350) * Math.exp(-contactT * 54) * .26 : 0
  return pan(soft(snap + relay + contact, 1.75), .02)
})

render('scan', .92, 120, (t, r) => {
  const sweep = sine(t, 180 + 1680 * Math.pow(Math.min(1, t / .68), 1.7)) * env(t, .02, .5, .04, .72, .16) * .25
  const carrier = sine(t, 57) * env(t, .03, .58, .08, .7, .18) * .28
  const ticks = Math.pow(Math.max(0, sine(t, 13)), 14) * .16
  const air = noiseBurst(t, r, 3.5) * env(t, .04, .6, 0, .74, .15) * .07
  return pan(soft(sweep + carrier + ticks + air), Math.sin(t * 7) * .48)
}, { echoes: [{ delay: .081, gain: .16 }, { delay: .162, gain: .08 }] })


// V2.1: closer structural matches for the five V1 groups selected by the user.
// Timing, weight, and pitch motion are references; every sample is synthesized.
const at = (t, start, fn) => t >= start ? fn(t - start) : 0
const metal = (x, base, decay = 15) =>
  (sine(x, base) * .46 + sine(x, base * 1.417) * .28 + sine(x, base * 2.113) * .16) * Math.exp(-x * decay)
const mechanicalHit = (x, random, base = 760, weight = 1) =>
  (click(x, random, base) * .42 + metal(x, base * .78, 22) * .38 + sine(x, 74) * Math.exp(-x * 25) * .22) * weight

render('21_startup', 3, 2101, (t, r) => {
  const bed = sine(t, 46 + 12 * Math.min(1, t / .5)) * env(t, .035, .72, .08, 1.18, .5) * .2
  const precharge = sine(t, 164 + 420 * Math.pow(Math.min(1, t / .5), 1.7)) * env(t, .05, .5, 0, .58, .12) * .14
  const pulse1 = at(t, .19, x => mechanicalHit(x, r, 520, .32))
  const pulse2 = at(t, .29, x => mechanicalHit(x, r, 720, .46))
  const pulse3 = at(t, .39, x => mechanicalHit(x, r, 930, .58))
  const main = at(t, .495, x => mechanicalHit(x, r, 1280, .92) + sine(x, 92) * Math.exp(-x * 4.6) * .48 + sine(x, 184) * Math.exp(-x * 6.2) * .2)
  const tail = at(t, .52, x => (sine(x, 780) * .12 + sine(x, 1170) * .07 + sine(x, 1563) * .045) * Math.exp(-x * 1.65) + noiseBurst(x, r, 1.5) * .035)
  return pan(soft(bed + precharge + pulse1 + pulse2 + pulse3 + main + tail, 1.45), Math.sin(t * 3.2) * .22)
}, { echoes: [{ delay: .052, gain: .14 }, { delay: .126, gain: .1 }, { delay: .248, gain: .055 }], peak: .94 })

render('21_download_start_coin', 1.296, 2102, (t, r) => {
  const coin = (start, base, gain) => at(t, start, x => (noiseBurst(x, r, 62) * .18 + metal(x, base, 9) + metal(x, base * 1.73, 13) * .34) * gain)
  return pan(coin(.118, 1760, .86) + coin(.205, 2110, .55) + coin(.425, 1570, .38) + coin(.592, 1930, .3) + coin(.705, 2240, .24) + coin(.93, 1680, .18), -.42 + Math.min(1, t / .95) * .8)
}, { echoes: [{ delay: .026, gain: .11 }, { delay: .061, gain: .07 }], peak: .72 })

render('21_download_start_token', .6, 2103, (t, r) => {
  const first = mechanicalHit(t, r, 1120, .82) + noiseBurst(t, r, 34) * .18
  const roller = tri(t, 138 + 12 * Math.sin(t * 31)) * env(t, .002, .22, 0, .34, .06) * .16
  const second = at(t, .052, x => mechanicalHit(x, r, 1440, .52))
  const dispense = at(t, .235, x => mechanicalHit(x, r, 920, .68) + metal(x, 2360, 18) * .28)
  const settle = at(t, .365, x => mechanicalHit(x, r, 620, .28))
  return pan(soft(first + roller + second + dispense + settle, 1.55), .26)
}, { echoes: [{ delay: .018, gain: .08 }], peak: .72 })

render('21_download_complete', 1.68, 2104, (t, r) => {
  const impact = mechanicalHit(t, r, 360, .65)
  const fundamental = sine(t, 238 - 28 * Math.min(1, t / .75)) * env(t, .002, .48, .03, 1.08, .24) * .45
  const chord = sine(t, 356) * env(t, .004, .44, .02, .92, .24) * .2 + sine(t, 474) * env(t, .008, .36, .015, .78, .2) * .11
  const confirm = at(t, .19, x => metal(x, 610, 8) * .23) + at(t, .4, x => metal(x, 720, 10) * .17)
  const texture = noiseBurst(t, r, 5.2) * env(t, .003, .55, 0, .82, .2) * .035
  return pan(soft(impact + fundamental + chord + confirm + texture, 1.35), -.06 + Math.sin(t * 4) * .15)
}, { echoes: [{ delay: .074, gain: .13 }, { delay: .148, gain: .065 }], peak: .86 })

render('21_install', .72, 2105, (t, r) => {
  const engage = at(t, .018, x => mechanicalHit(x, r, 980, .68))
  const slide = at(t, .048, x => noiseBurst(x, r, 14) * Math.exp(-x * 5) * .14 + tri(x, 92) * Math.exp(-x * 7) * .12)
  const mid = at(t, .105, x => mechanicalHit(x, r, 720, .42))
  const latch = at(t, .198, x => mechanicalHit(x, r, 1680, .92) + sine(x, 96) * Math.exp(-x * 13) * .3)
  const verify = at(t, .39, x => mechanicalHit(x, r, 1180, .62) + metal(x, 2440, 16) * .24)
  return pan(soft(engage + slide + mid + latch + verify, 1.65), -.18 + t * .42)
}, { echoes: [{ delay: .021, gain: .09 }, { delay: .057, gain: .06 }], peak: .9 })

render('21_success_tactile', .68, 2106, (t, r) => {
  const snap = noiseBurst(t, r, 58) * .27 + mechanicalHit(t, r, 1820, .66)
  const bright = metal(t, 3100, 17) * .22
  const tinyReturn = at(t, .095, x => mechanicalHit(x, r, 1280, .24))
  return pan(soft(snap + bright + tinyReturn, 1.6), .04)
}, { echoes: [{ delay: .016, gain: .06 }], peak: .82 })

render('21_success_coin', .6, 2107, (t, r) => {
  const strike = noiseBurst(t, r, 72) * .12 + metal(t, 1885, 13) * .54
  const upper = metal(t, 2870, 17) * .32 + metal(t, 4010, 22) * .14
  const bounce = at(t, .034, x => metal(x, 2340, 17) * .26)
  return pan(strike + upper + bounce, .28)
}, { echoes: [{ delay: .028, gain: .09 }, { delay: .056, gain: .05 }], peak: .82 })

console.log(`Generated ModAgent V2 sound pack: ${outDir}`)
