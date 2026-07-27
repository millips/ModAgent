const PAGE_GATE_PATTERN = /Cloudflare|人机验证|安全验证|验证码|登录(?:页面|账号)?|成人(?:内容|确认)|年龄确认|Manual Download|Slow Download|手动下载页面/i
const USER_ACTION_PATTERN = /需要你操作|请在(?:已经)?打开的.*页面|请先完成|完成后(?:告诉我|回来|再试|继续)|验证完成后|登录完成后/i
const RESUME_PATTERN = /继续(?:下载|安装|处理|刚才)|立刻继续|随后继续|完成后告诉我/i

export const PAGE_GATE_COMPLETED_REPLY = {
  label: '完成了',
  message: (
    '我已经完成刚才要求的页面操作。请只继续同一个被中断的下载或安装目标，'
    + '复用现有页面和已经完成的步骤；不要重新搜索、不要更换目标，'
    + '也不要重复已经成功的下载或安装。'
  ),
}

export function getManualActionQuickReply(content) {
  const text = String(content || '').replace(/\s+/g, ' ').trim()
  if (!text) return null
  if (!PAGE_GATE_PATTERN.test(text)) return null
  if (!USER_ACTION_PATTERN.test(text)) return null
  if (!RESUME_PATTERN.test(text)) return null
  return PAGE_GATE_COMPLETED_REPLY
}
