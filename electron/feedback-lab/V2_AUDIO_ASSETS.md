# ModAgent V2 original sound pack

The V2 comparison sounds are generated from source by
`generate_v2_soundpack.js`.

- No samples or waveform fragments are copied from the V1 MP3 files.
- V1 is used only as a functional reference for timing, weight, and interaction intent.
- Every V2 waveform is synthesized from oscillators, deterministic noise,
  envelopes, saturation, stereo positioning, and delay.
- Output format: stereo PCM WAV, 48 kHz, 16-bit.
- Output folder: `%USERPROFILE%\Desktop\音频素材\ModAgent_V2`.

The generator seed and parameters are committed with the project so every
sound can be reproduced, adjusted, and audited.

Current V2 events:

- startup
- hover
- press
- download start (coin + token)
- download complete
- install
- success (tactile + coin)
- notice
- remove (primary + secondary)
- snapshot
- rollback
- warning / destructive warning
- error (primary + secondary)
- cancel
- enable / disable
- scan
