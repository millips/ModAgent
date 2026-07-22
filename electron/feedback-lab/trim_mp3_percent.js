const fs = require('fs')

const [input, output, ratioText] = process.argv.slice(2)
const ratio = Number(ratioText)
if (!input || !output || !(ratio > 0 && ratio < 1)) throw new Error('usage: input output ratio')
const data = fs.readFileSync(input)

let offset = 0
if (data.toString('ascii', 0, 3) === 'ID3' && data.length >= 10) {
  const size = ((data[6] & 0x7f) << 21) | ((data[7] & 0x7f) << 14) | ((data[8] & 0x7f) << 7) | (data[9] & 0x7f)
  offset = 10 + size
}

const bitrateV1L3 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320]
const bitrateV2L3 = [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160]
const rates = {3:[44100,48000,32000],2:[22050,24000,16000],0:[11025,12000,8000]}
const frames = []
for (let i = offset; i + 4 <= data.length;) {
  if (data[i] !== 0xff || (data[i+1] & 0xe0) !== 0xe0) { i++; continue }
  const version = (data[i+1] >> 3) & 3
  const layer = (data[i+1] >> 1) & 3
  const bitrateIndex = (data[i+2] >> 4) & 15
  const rateIndex = (data[i+2] >> 2) & 3
  const padding = (data[i+2] >> 1) & 1
  if (version === 1 || layer !== 1 || bitrateIndex === 0 || bitrateIndex === 15 || rateIndex === 3) { i++; continue }
  const bitrate = (version === 3 ? bitrateV1L3 : bitrateV2L3)[bitrateIndex] * 1000
  const sampleRate = rates[version][rateIndex]
  const frameSize = Math.floor((version === 3 ? 144 : 72) * bitrate / sampleRate) + padding
  if (frameSize < 24 || i + frameSize > data.length) break
  frames.push({start:i, end:i+frameSize})
  i += frameSize
}
if (frames.length < 2) throw new Error('No valid MP3 frames found')

const cutIndex = Math.min(frames.length - 1, Math.max(1, Math.round(frames.length * ratio)))
fs.writeFileSync(output, data.subarray(frames[cutIndex].start, frames[frames.length - 1].end))
console.log(JSON.stringify({frames:frames.length, cutIndex, retainedFrames:frames.length-cutIndex, ratio}))
