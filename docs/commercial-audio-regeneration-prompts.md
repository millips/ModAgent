# ModAgent 商用音效重建提示词

状态：2026-07-17 重建版。  
用途：在 ElevenLabs 付费订阅期内重新生成订阅版音效。  
说明：这些提示词依据 V1 的事件用途、文件名线索和已确认听感重建，不宣称是遗失提示词的逐字原文。

## 统一生成要求

- 使用正式版 Sound Effects，不使用 Beta 服务。
- 每条生成 4–8 个候选。
- isolated、close-miked、dry、no ambience、no music、no voice。
- 不引用游戏、电影、品牌、枪械型号或第三方作品名称。
- 下载原始 MP3/WAV，并保存提示词、生成历史截图和生成时间。
- 最终入选文件增加 `商用-` 前缀，不覆盖免费期 V1。

## 01 悬浮 `ui-hover.mp3`

```text
An extremely subtle premium futuristic UI hover sound: a tiny airy electrostatic shimmer and one microscopic glassy high-frequency tick, soft, elegant, clean and almost weightless. It should acknowledge cursor hover without demanding attention. One cohesive micro gesture.

Duration: 0.22 seconds.
Priority weights: subtle hover feedback 1.5; airy digital shimmer 1.25; tiny glass tick 1.1; softness 1.4.
No click, no bass, no impact, no melody, no reverb, no ambience, no noise.
```

## 02 按下 `ui-press.mp3`

```text
A short premium sci-fi UI button press with a soft tactile membrane compression, a precise low mechanical micro-click, and an immediate clean electronic release. Dense, controlled, addictive and responsive, like pressing a high-end illuminated control surface.

Duration: 0.32 seconds.
Timing: 0.00–0.10s soft compression 35%; 0.08–0.18s precise tactile click 100%; 0.16–0.32s tiny electronic release 35%.
Priority weights: tactile press 1.5; compact mechanical click 1.35; premium UI 1.35; short release 0.8.
No keyboard, no mouse click, no arcade tone, no music, no ambience, no long tail.
```

## 03 安装完成主层 `success-tactile.mp3`

```text
A compact futuristic module-lock confirmation. A small precision mechanism slides the final millimeter into place, followed by a firm clean latch click and a restrained bright electronic confirmation sparkle. Satisfying, secure and premium.

Duration: 0.55 seconds.
Timing: 0.00–0.16s short guided insertion 45%; 0.15–0.30s firm lock-in click 100%; 0.28–0.55s restrained confirmation shimmer 45%.
Priority weights: mechanical lock 1.5; tactile completion 1.45; compact sci-fi mechanism 1.3; bright confirmation 0.8.
No weapon, no gun, no coin, no melody, no ambience, no cinematic impact.
```

## 04 安装完成奖励层 `success-coin.mp3`

```text
A single tiny premium digital reward token landing into a precision metal receiver: one bright clean metallic ping with a very short sparkling electronic overtone. Refined and restrained, suitable as a secondary layer after a successful installation.

Duration: 0.38 seconds.
Priority weights: single reward ping 1.5; clean metal-glass tone 1.25; tiny digital sparkle 0.9; short decay 1.2.
No arcade game, no cash register, no multiple coins, no bouncing, no music, no ambience.
```

## 05 快照完成 `snapshot-complete.mp3`

```text
A premium futuristic snapshot-save sound inspired by gently peeling and resealing a soft silicone membrane. Begin with a smooth elastic separation, then a subtle suction release and a clean soft seal locking into place. Tactile, organic-tech, calm and deeply satisfying.

Duration: 0.95 seconds.
Timing: 0.00–0.34s soft elastic peel 65%; 0.30–0.55s controlled suction release 45%; 0.52–0.82s membrane reseal 80%; 0.80–0.95s tiny digital confirmation 25%.
Priority weights: soft silicone peel 1.45; elastic membrane 1.35; clean reseal 1.4; organic technology 1.2.
No tearing damage, no sticky slime, no horror texture, no wet liquid, no ambience, no music.
```

## 06 回滚 `rollback.mp3`

```text
A compact futuristic rollback sound. A precision rotary mechanism spins clockwise once, reaches a brief elastic tension stop, then releases and rapidly rewinds counter-clockwise twice with a smooth descending electronic time-reversal sweep. Fluid, controlled and clearly reversible.

Duration: 0.85 seconds.
Timing: 0.00–0.24s clockwise wind-up 65%; 0.24–0.31s tension hold 90%; 0.31–0.72s faster counter-clockwise double rewind 100%; 0.72–0.85s soft reverse lock 45%.
Priority weights: mechanical rewind 1.5; elastic tension release 1.4; reverse time sweep 1.35; smooth rotation 1.3.
No alarm, no error buzz, no tape noise, no music, no ambience, no impact.
```

## 07 轻提示 `notice.mp3`

```text
A soft subtle premium UI text notification: one delicate glassy bling supported by a faint airy digital shimmer. Calm, informative and polished, clearly audible but never urgent.

Duration: 0.70 seconds.
Priority weights: soft notification 1.5; delicate glass ping 1.25; airy shimmer 0.85; restrained tail 1.1.
No warning, no phone message tone, no melody, no bass, no ambience, no long reverb.
```

## 08 卸载主层 `remove-primary.mp3`

```text
A short precision mechanical release sound: a compact locking catch disengages, a spring-loaded handle snaps backward, and the mechanism becomes free. Crisp, tactile and controlled, designed for removing a software module.

Duration: 0.48 seconds.
Timing: 0.00–0.14s lock disengage 80%; 0.12–0.30s spring release 100%; 0.28–0.48s short metal settle 35%.
Priority weights: mechanical release 1.5; spring snap 1.3; lock disengage 1.4; compact mechanism 1.25.
No firearm, no gunshot, no shell casing, no heavy impact, no ambience, no music.
```

## 09 卸载收尾层 `remove-secondary.mp3`

```text
A short premium downward technological power-down sweep ending in a muted mechanical disconnect click. Clean, restrained and conclusive, suitable as the secondary layer of a module removal action.

Duration: 0.62 seconds.
Priority weights: downward electronic sweep 1.45; clean disconnect 1.35; muted final click 1.1; premium system sound 1.25.
No failure alarm, no dramatic shutdown, no bass boom, no music, no ambience, no long tail.
```

## 10 取消/撤销 `cancel.mp3`

```text
A concise premium cancel-button sound: a soft reverse digital flick, followed by a tiny damped tactile click that gently closes the action. Neutral, clean and non-threatening.

Duration: 0.32 seconds.
Priority weights: cancel feedback 1.5; soft reverse flick 1.25; damped tactile close 1.2; neutral UI tone 1.35.
No error alarm, no warning, no negative buzzer, no melody, no ambience, no reverb.
```

## 11 启用/禁用 `toggle.mp3`

```text
A compact premium on-off toggle sound inspired by a fingertip striking the surface tension of clean water, transformed into a futuristic switch. One crisp liquid-glass tick with a tight mechanical toggle underneath and an extremely short resonant ripple.

Duration: 0.36 seconds.
Priority weights: tactile toggle 1.5; crisp liquid-glass tick 1.25; mechanical switch 1.35; short ripple 0.65.
No splash, no dripping water, no wet ambience, no melody, no long reverb.
```

## 12 扫描 `scan.mp3`

```text
A premium futuristic system scan sound. A focused electronic pulse launches, a narrow spectral beam sweeps rapidly from low to high frequency, then returns one clean analytical confirmation ping. Precise, sophisticated and restrained.

Duration: 1.35 seconds.
Timing: 0.00–0.16s scan launch pulse 55%; 0.12–0.92s smooth spectral sweep 85%; 0.90–1.18s data focus 50%; 1.15–1.35s clean result ping 70%.
Priority weights: analytical scan sweep 1.5; focused electronic beam 1.35; premium technology 1.3; clean result ping 1.0.
No radar beeps, no sonar ambience, no spaceship background, no music, no voice, no alarm.
```

## 13 操作失败主层 `error-primary.mp3`

```text
A premium futuristic operation-failed sound with a compact low-frequency electronic rejection pulse, a short descending synthetic bend, and a controlled muted impact. Authoritative and clear without becoming frightening or cinematic.

Duration: 0.72 seconds.
Priority weights: clear failure feedback 1.5; low electronic rejection pulse 1.35; short descending bend 1.3; controlled impact 1.0.
No explosion, no horror, no siren, no voice, no music, no ambience, no huge bass boom.
```

## 14 操作失败辅层 `error-secondary.mp3`

```text
A short cold error-notification accent: two tightly spaced precise digital fault ticks, the second slightly lower and dimmer, ending immediately. Designed as a secondary layer over a low failure pulse.

Duration: 0.42 seconds.
Timing: first fault tick at 0.05s; second lower tick at 0.18s; silence after 0.38s.
Priority weights: precise error ticks 1.5; cold digital character 1.25; short duration 1.4; secondary-layer clarity 1.2.
No alarm loop, no phone notification, no melody, no ambience, no reverb.
```

## 推荐实装参数

| 事件 | 文件 | 增益 | 延迟 | 速度 |
|---|---|---:|---:|---:|
| 悬浮 | ui-hover | 50% | 0ms | 1.0× |
| 按下 | ui-press | 50% | 0ms | 1.0× |
| 安装完成 | success-tactile | 82% | 0ms | 1.0× |
| 安装完成 | success-coin | 48% | 150ms | 1.0× |
| 快照 | snapshot-complete | 100% | 0ms | 1.0× |
| 回滚 | rollback | 100% | 0ms | 1.0× |
| 轻提示 | notice | 75% | 0ms | 1.0× |
| 卸载 | remove-primary | 72% | 0ms | 1.0× |
| 卸载 | remove-secondary | 56% | 110ms | 1.0× |
| 取消 | cancel | 100% | 0ms | 1.0× |
| 启用/禁用 | toggle | 200% | 0ms | 1.0× |
| 扫描 | scan | 100% | 0ms | 1.0× |
| 失败 | error-primary | 88% | 0ms | 1.0× |
| 失败 | error-secondary | 62% | 90ms | 1.0× |

