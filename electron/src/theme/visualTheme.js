export const VISUAL_THEMES = [
  { value: 'cat', label: '猫咪夜航', note: '精致猫咪装饰、柔和月光与分级容器', controls: 'theme' },
  { value: 'gothic', label: '哥特圣堂', note: '黑曜石圣堂、暗红彩窗与旧银雕花', controls: 'theme' },
  { value: 'tactical', label: '战术军械库', note: '石墨装甲、琥珀光学与精密导轨', controls: 'theme' },
  { value: 'abyssal', label: '深渊秘典', note: '黑海星仪、古老黄铜与幽微虹膜', controls: 'theme' },
  { value: 'core', label: '默认冷蓝', note: 'ModAgent 原版冷蓝控制台与大按钮', controls: 'classic' },
  { value: 'modern-tech', label: '现代科技', note: '石墨、银白、克制青光与原版大按钮', controls: 'classic' },
  { value: 'cyber', label: '赛博霓虹', note: '紫、青、玫红高对比霓虹', controls: 'minimal-tech' },
  { value: 'galgame', label: '日式暖金', note: '暖金、紫藤与低饱和玻璃', controls: 'minimal-tech' },
  { value: 'soft', label: '柔光粉雾', note: '柔和粉紫与圆润表面', controls: 'minimal-tech' },
  { value: 'kawaii', label: '樱语可爱', note: '日系女性向、蝴蝶结与柔粉珠光', controls: 'theme' },
  { value: 'minimal', label: '极简黑金', note: '低干扰黑灰与克制金色', controls: 'minimal-tech' },
  { value: 'pixel', label: '像素 CRT', note: '绿色终端、蓝色信号与扫描线', controls: 'minimal-tech' },
]

export const LIGHTING_MODES = [
  { value: 'auto', label: '智能平衡' },
  { value: 'cozy', label: '温馨暖光' },
  { value: 'energetic', label: '活力霓虹' },
  { value: 'romantic', label: '微醺浪漫' },
  { value: 'focus', label: '深夜独酌' },
]

const KEYS = {
  visual: 'modagent-subscription-visual-theme',
  lighting: 'modagent-subscription-lighting',
}

function read(key, fallback) {
  try { return localStorage.getItem(key) || fallback }
  catch (_) { return fallback }
}

export function readVisualPreferences() {
  return {
    visual: read(KEYS.visual, 'core'),
    lighting: read(KEYS.lighting, 'auto'),
  }
}

export function applyVisualPreferences(preferences) {
  const visual = preferences.visual || 'core'
  const lighting = preferences.lighting || 'auto'
  const controls = VISUAL_THEMES.find(item => item.value === visual)?.controls || 'minimal-tech'
  document.body.classList.add('theme-technology-core')
  document.body.classList.toggle('theme-classic-controls', controls === 'classic')
  document.body.classList.toggle('theme-minimal-tech', controls === 'minimal-tech')
  document.body.dataset.maTheme = visual
  document.body.dataset.maLighting = lighting
}

export function clearVisualPreferences() {
  document.body.classList.remove('theme-technology-core', 'theme-classic-controls', 'theme-minimal-tech')
  delete document.body.dataset.maTheme
  delete document.body.dataset.maLighting
}

export function saveVisualPreference(key, value) {
  if (!KEYS[key]) return
  try { localStorage.setItem(KEYS[key], value) } catch (_) {}
  applyVisualPreferences({ ...readVisualPreferences(), [key]: value })
}
