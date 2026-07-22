const fs = require('fs')
const path = require('path')

const sampleRate = 48000
const duration = 0.62
const samples = Math.floor(sampleRate * duration)
const pcm = Buffer.alloc(samples * 2)
let seed = 7331
const noise = () => ((seed = (seed * 16807) % 2147483647) / 1073741823.5) - 1

let phase1 = 0, phase2 = 0, phase3 = 0
for (let i = 0; i < samples; i++) {
  const t = i / sampleRate
  const attack = Math.min(1, t / 0.008)
  const decay = Math.exp(-t * 7.4)
  const envelope = attack * decay
  // Tiny downward pitch bend gives the pulse a physical, voltage-driven weight.
  const f = 67 + 18 * Math.exp(-t * 18)
  phase1 += 2 * Math.PI * f / sampleRate
  phase2 += 2 * Math.PI * (f * 0.5) / sampleRate
  phase3 += 2 * Math.PI * (f * 2.01) / sampleRate
  const fundamental = Math.sin(phase1) * 0.58
  const sub = Math.sin(phase2) * 0.24
  const harmonic = Math.sin(phase3) * 0.10
  const transient = noise() * 0.16 * Math.exp(-t * 65)
  const electrical = Math.sin(2 * Math.PI * 1180 * t) * 0.055 * Math.exp(-t * 28)
  let value = (fundamental + sub + harmonic) * envelope + transient + electrical
  // Soft analog saturation rather than hard clipping.
  value = Math.tanh(value * 1.32) * 0.78
  pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(value * 32767))), i * 2)
}

const header = Buffer.alloc(44)
header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVE', 8)
header.write('fmt ', 12); header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20)
header.writeUInt16LE(1, 22); header.writeUInt32LE(sampleRate, 24)
header.writeUInt32LE(sampleRate * 2, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34)
header.write('data', 36); header.writeUInt32LE(pcm.length, 40)

const output = path.join(__dirname, '低沉模拟合成器脉冲_01.wav')
fs.writeFileSync(output, Buffer.concat([header, pcm]))
console.log(output)
