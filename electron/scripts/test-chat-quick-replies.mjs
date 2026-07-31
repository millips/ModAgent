import assert from 'node:assert/strict'
import {
  getManualActionQuickReply,
  PAGE_GATE_COMPLETED_REPLY,
} from '../src/components/chatQuickReplies.mjs'

const cloudflarePrompt = `
Nexus 弹了 Cloudflare 人机验证（"正在进行安全验证"）。
需要你操作：请在打开的 Nexus 页面中完成人机验证，完成后告诉我，我立刻继续下载。
`
assert.deepEqual(
  getManualActionQuickReply(cloudflarePrompt),
  PAGE_GATE_COMPLETED_REPLY,
)

assert.deepEqual(
  getManualActionQuickReply('请先完成 Nexus 登录，登录完成后告诉我，我会继续刚才的安装。'),
  PAGE_GATE_COMPLETED_REPLY,
)

assert.equal(
  getManualActionQuickReply('安装计划已经生成。确认安装吗？(y/n)'),
  null,
)
assert.equal(
  getManualActionQuickReply('Cloudflare 是一种常见的站点安全防护服务。'),
  null,
)
assert.equal(
  getManualActionQuickReply('Mod 安装完成。'),
  null,
)

console.log('chat quick reply tests passed')
