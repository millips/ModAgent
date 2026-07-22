export const VISUAL_THEMES = [
  { value: 'cat', label: '猫咪夜航', note: '精致猫咪装饰、柔和月光与分级容器' },
  { value: 'gothic', label: '哥特圣堂', note: '黑曜石圣堂、暗红彩窗与旧银雕花' },
  { value: 'tactical', label: '战术军械库', note: '石墨装甲、琥珀光学与精密导轨' },
  { value: 'abyssal', label: '深渊秘典', note: '黑海星仪、古老黄铜与幽微虹膜' },
  { value: 'core', label: '科技核心', note: 'ModAgent 默认冷蓝控制台' },
  { value: 'modern-tech', label: '现代科技', note: '石墨、银白与克制青光' },
  { value: 'cyber', label: '赛博霓虹', note: '紫、青、玫红高对比霓虹' },
  { value: 'galgame', label: '日式暖金', note: '暖金、紫藤与低饱和玻璃' },
  { value: 'soft', label: '柔光粉雾', note: '柔和粉紫与圆润表面' },
  { value: 'kawaii', label: '樱语可爱', note: '日系女性向、蝴蝶结与柔粉珠光' },
  { value: 'minimal', label: '极简黑金', note: '低干扰黑灰与克制金色' },
  { value: 'pixel', label: '像素 CRT', note: '绿色终端、蓝色信号与扫描线' },
]

export const LIGHTING_MODES = [
  { value: 'auto', label: '智能平衡' },
  { value: 'cozy', label: '温馨暖光' },
  { value: 'energetic', label: '活力霓虹' },
  { value: 'romantic', label: '微醺浪漫' },
  { value: 'focus', label: '深夜独酌' },
]

const KEYS = {
  controls: 'modagent-subscription-controls',
  visual: 'modagent-subscription-visual-theme',
  lighting: 'modagent-subscription-lighting',
}

function read(key, fallback) {
  try { return localStorage.getItem(key) || fallback }
  catch (_) { return fallback }
}

export function readVisualPreferences() {
  let legacyControls = 'classic'
  try { legacyControls = localStorage.getItem('modagent-ui-theme') || 'classic' } catch (_) {}
  return {
    controls: read(KEYS.controls, legacyControls),
    visual: read(KEYS.visual, 'core'),
    lighting: read(KEYS.lighting, 'auto'),
  }
}

export function applyVisualPreferences(preferences) {
  const controls = preferences.controls || 'classic'
  const visual = preferences.visual || 'core'
  const lighting = preferences.lighting || 'auto'
  document.body.classList.add('theme-technology-core')
  document.body.classList.toggle('theme-classic-controls', controls === 'classic')
  document.body.classList.toggle('theme-minimal-tech', controls === 'minimal-tech')
  document.body.dataset.maTheme = visual
  document.body.dataset.maLighting = lighting
}

export function saveVisualPreference(key, value) {
  if (!KEYS[key]) return
  try { localStorage.setItem(KEYS[key], value) } catch (_) {}
  applyVisualPreferences({ ...readVisualPreferences(), [key]: value })
}
