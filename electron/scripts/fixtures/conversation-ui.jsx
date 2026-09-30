import React from 'react'
import { createRoot } from 'react-dom/client'
import ChatPage from '../../src/components/ChatPage'

window.fixtureRequests = []
window.fixtureErrors = []
const item = {
  selection_key: 'nexus:42', source: 'nexus', source_id: '42', mod_id: '42',
  name: 'Training UI Helper [TEST FIXTURE]', summary: 'Training assistance and clearer UI for Fixture Game.',
  description: 'Training assistance and clearer UI for Fixture Game.',
  url: 'https://www.nexusmods.com/fixturegame/mods/42', version: '1.0',
  detail_verified: true, installable: true, default_selected: false, conflict_status: 'clear',
  goal_fit: { status: 'matched', evidence: ['Clearer UI and information display.'] },
  selection_reason: '未预选：请核对功能匹配、重复功能或安装条件',
  variants: [
    { variant_id: '42:101', file_id: '101', name: 'Standard', file_name: 'standard.zip', is_primary: true },
    { variant_id: '42:102', file_id: '102', name: 'Large UI', file_name: 'large-ui.zip' },
  ],
}
let serial = 0
const response = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
window.fetch = async (input, options = {}) => {
  const url = String(input)
  const body = options.body ? JSON.parse(options.body) : {}
  window.fixtureRequests.push({ url, body, method: options.method || 'GET' })
  if (url.includes('/chat/tasks/active')) return response({ active: false })
  if (url.endsWith('/downloads/status')) return response({ active: false })
  if (url.includes('/sessions') && options.method === 'POST') return response({ id: 'fixture-session' })
  if (url.includes('/sessions') && !options.method) return response([])
  if (url.endsWith('/tasks/saved-task/resume')) return response({
    ok: true, action: 'rebuild_plan', recovery_task_id: 'saved-task', session_id: 'fixture-session',
    recommendation_selection: [{ ...item, file_id: '102', variant_id: '42:102', variant_name: 'Large UI' }],
    message: '恢复原选择，重新核验计划；不要下载安装。',
  })
  if (url.endsWith('/chat/stream')) {
    const task = `ui-${++serial}`
    const terminal = (state, summary, extra = {}) => ({ task_event: {
      task_id: task, seq: 5, state, type: state === 'WAITING_CONFIRMATION' ? 'decision_required' : state === 'COMPLETED' ? 'task_completed' : 'task_failed',
      payload: { result: { summary, completed: [], not_completed: [], warnings: [] }, ...extra },
    } })
    let events
    if (body.selection_action === 'plan') {
      const ready = terminal('WAITING_CONFIRMATION', '本轮核验结束，请查看待确认清单。', {
        plan_revision: { task_id: task, revision_id: `plan-${task}` },
      })
      ready.task_event.payload.result.not_completed = [{reason:'waiting_for_confirmation'}]
      ready.task_event.payload.result.next_actions = [{action:'confirm_or_adjust_plan'}]
      events = [{ chunk: '已核验测试目标；请在卡片中选择变体并确认。' }, ready]
    } else if (body.selection_action === 'confirm') {
      events = [{ tool_result: { name: 'mod_install_batch', ok: true, outcome_status: 'success', execution_complete: true, all_selected_installed: true, summary: 'Fixture receipt only; no files were installed.' } },
        { chunk: '模拟执行完成：没有联网下载，没有修改游戏文件。' }, terminal('COMPLETED', '测试完成。')]
    } else if (body.message === '?何意味') {
      events = [{chunk:'上一轮停在等待确认，并不是安装完成。本轮只解释，不恢复搜索、下载或安装。'},
        terminal('COMPLETED', '说明已有状态。', {presentation:{show_card:false}})]
    } else if (body.message.includes('模拟中断恢复')) {
      const failed = terminal('FAILED', '测试任务中断，原选择已保留。', { recovery_available: true })
      failed.task_event.task_id = 'saved-task'
      events = [{ chunk: '测试任务中断，原选择已保留。' }, failed]
    } else if (body.message.includes('搜')) {
      events = [{ progress: {stage:'source_search',label:'来源已返回 0/2；等待：Nexus, GitHub'} },
        {progress: {stage:'source_detail',label:'Nexus 详情核验已返回 1/2 项'}},
        {progress: {stage:'heartbeat',label:'任务仍在进行，等待当前步骤返回'}},
        {progress: {stage:'source_search',label:'来源已返回 2/2；等待：—'}},
        { recommendations: { kind: 'recommendation_set', items: [item], selected_keys: [], source_counts: { nexus: 1 } } },
        { chunk: '找到 1 个测试候选，请在清单中选择。' }, terminal('COMPLETED', '搜索结束。')]
    } else {
      events = [{ chunk: '**Mod** 是游戏的修改或扩展。' }, terminal('COMPLETED', '已回答本轮问题。', { presentation: { show_card: false } })]
    }
    events.push({ done: true })
    const encoder = new TextEncoder()
    return new Response(new ReadableStream({ start(controller) {
      events.forEach(event => controller.enqueue(encoder.encode('data: ' + JSON.stringify(event) + '\n\n')))
      controller.close()
    } }), { headers: { 'Content-Type': 'text/event-stream', 'X-ModAgent-Session': 'fixture-session' } })
  }
  return response({ ok: true })
}
createRoot(document.getElementById('root')).render(<ChatPage
  status={{ online: true, game: 'Fixture Game', game_slug: 'fixturegame', game_root: 'C:/TEST-ONLY', mods: 0, snaps: 0 }}
  games={[]} onGameChange={() => {}} onRefresh={() => {}} toast={text => window.fixtureErrors.push(text)} api="http://fixture.invalid" />)
