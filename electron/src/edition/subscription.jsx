import React, { useState } from 'react'
import { Bell, Check, ListChecks, Palette, Pencil, RotateCcw, ShieldAlert, Volume2 } from 'lucide-react'
import FeedbackCore from '../components/FeedbackCore'
import { emitFeedback } from '../feedback/feedbackBus'
import {
  getFeedbackSoundVolume,
  resetFeedbackSoundVolumes,
  setFeedbackSoundVolume,
} from '../feedback/feedbackAudio'
import { installFeedbackInteractions } from '../feedback/feedbackInteractions'
import {
  VISUAL_THEMES,
  LIGHTING_MODES,
  applyVisualPreferences,
  readVisualPreferences,
  saveVisualPreference,
} from '../theme/visualTheme'

export { RecommendationDecisionTable as ChatEditionMessage } from '../components/RecommendationDecisionTable'

const FEEDBACK_TESTS = [
  ['hover', 'UI.01', '悬浮'],
  ['press', 'UI.02', '普通按压'],
  ['manual', 'UI.03', '大旋钮按压'],
  ['reply-complete', 'MSG.01', '回复完成'],
  ['startup', 'SYS.00', '系统启动'],
  ['download-start', 'DL.01', '下载开始'],
  ['download-item-complete', 'DL.02', '单项下载完成'],
  ['download-batch-complete', 'DL.03', '下载批次完成'],
  ['install-start', 'DEP.01', '开始部署'],
  ['install-complete', 'DEP.02', '安装完成'],
  ['install-batch-complete', 'DEP.03', '批量安装完成', 6],
  ['snapshot-complete', 'SNP.01', '创建快照'],
  ['rollback-complete', 'SNP.02', '回滚快照'],
  ['remove-complete', 'MOD.00', '卸载 / 删除'],
  ['scan-start', 'SCN.01', '扫描开始'],
  ['scan-complete', 'SCN.02', '扫描完成'],
  ['success', 'ACK.01', '确认成功'],
  ['notice', 'ACK.02', '轻提示'],
  ['cancel', 'ACK.03', '取消'],
  ['enable', 'PWR.01', '启用'],
  ['disable', 'PWR.02', '禁用'],
  ['warning', 'ALT.01', '普通警告'],
  ['destructive', 'ALT.02', '危险确认'],
  ['error', 'ERR.00', '错误'],
].map(([type, code, label, count]) => ({ type, code, label, count }))

export function bootstrapEdition() {
  applyVisualPreferences(readVisualPreferences())
  installFeedbackInteractions()
}

export function SidebarEditionAddon({ page }) {
  return <FeedbackCore page={page} />
}

const conflictTone = {
  warning: 'border-cyber-yellow/30 bg-cyber-yellow/10 text-cyber-yellow',
  danger: 'border-cyber-red/30 bg-cyber-red/10 text-cyber-red',
  clear: 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green',
  unknown: 'border-surface-600 bg-surface-800 text-surface-400',
}

function LegacyChatEditionMessage({
  message, onChange, onSubmit, disabled = false,
}) {
  if (message?.payload?.kind !== 'recommendation_set') return null
  const payload = message.payload
  const items = Array.isArray(payload.items) ? payload.items : []
  const selected = new Set(payload.selected_keys || [])
  const phase = ['confirm', 'executing', 'completed'].includes(payload.phase)
    ? payload.phase : 'recommendation'
  const isConfirmation = phase !== 'recommendation'
  const locked = phase === 'executing' || phase === 'completed'
  const selectedItems = items.filter(item => selected.has(item.selection_key))
  const selectableKeys = items.filter(item => item.installable !== false).map(item => item.selection_key)
  const defaults = items.filter(item => item.default_selected).map(item => item.selection_key)
  const sourceCount = new Set(items.map(item => item.source).filter(Boolean)).size
  const verifiedCount = items.filter(item => item.detail_verified).length
  const unavailableCount = items.filter(item => item.installable === false).length
  const verificationCoverage = items.length
    ? Math.round((verifiedCount / items.length) * 100)
    : 100

  const update = keys => onChange?.([...new Set(keys)])
  const toggle = key => {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    update([...next])
  }

  return (
    <section className="pro-recommendation-panel w-full overflow-hidden rounded-xl border border-cyber-cyan/25 bg-surface-900/85 shadow-[0_0_24px_rgba(0,212,255,0.08)]">
      <div className="pro-recommendation-header flex flex-wrap items-start justify-between gap-4 border-b border-surface-700/80 px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            {isConfirmation
              ? <ShieldAlert size={16} className="text-cyber-yellow" />
              : <ListChecks size={16} className="text-cyber-cyan" />}
            {phase === 'executing'
              ? '安装流程执行中 · 选择已锁定'
              : phase === 'completed'
                ? '安装流程已提交'
                : isConfirmation
                  ? '安装确认 · 最终选择'
                  : 'Pro 智能推荐 · 决策清单'}
          </div>
          <p className="mt-1.5 max-w-3xl text-[11px] leading-relaxed text-surface-500">
            {isConfirmation
              ? '确认前仍可取消或增添；实际安装只处理最终勾选项及核实后的必需依赖。'
              : '结合本轮搜索、详情核验、更新活跃度与依赖信息整理。已预选优先候选，但最终兼容性仍需在下载包和目标游戏版本上确认。'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-surface-400">
            <span className="pro-recommendation-stat">{items.length} 个候选</span>
            <span className="pro-recommendation-stat">{sourceCount || 1} 个来源</span>
            <span className="pro-recommendation-stat">{verifiedCount} 项详情已核验</span>
            <span className={`pro-recommendation-stat ${
              verificationCoverage < 95 ? 'is-warning' : ''
            }`}>核验覆盖 {verificationCoverage}%</span>
            {unavailableCount > 0 && (
              <span className="pro-recommendation-stat is-warning">{unavailableCount} 项暂不可安装</span>
            )}
          </div>
        </div>
        <div className="rounded-full border border-cyber-cyan/20 bg-cyber-cyan/10 px-3 py-1.5 text-[11px] font-medium text-cyber-cyan">
          已选 {selectedItems.length} / {items.length}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="pro-recommendation-table w-full min-w-[1040px] table-fixed text-left text-xs">
          <thead className="bg-surface-800/90 text-[10px] uppercase tracking-wider text-surface-500">
            <tr>
              <th className="w-14 px-3 py-3 text-center">选择</th>
              <th className="w-56 px-3 py-3">Mod</th>
              <th className="w-[23rem] px-3 py-3">功能与推荐依据</th>
              <th className="w-36 px-3 py-3">版本 / 活跃度</th>
              <th className="w-56 px-3 py-3">兼容风险与依赖</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/70">
            {items.map((item, index) => {
              const checked = selected.has(item.selection_key)
              const unavailable = item.installable === false
              return (
                <tr
                  key={item.selection_key}
                  className={`${checked ? 'bg-cyber-cyan/[0.045]' : 'bg-transparent'} ${unavailable ? 'opacity-55' : 'hover:bg-white/[0.025]'}`}
                >
                  <td className="px-3 py-3 text-center">
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      aria-label={`选择 ${item.name}`}
                      disabled={disabled || locked || unavailable}
                      onClick={() => toggle(item.selection_key)}
                      className={`mx-auto flex h-5 w-5 items-center justify-center rounded border transition-colors ${
                        checked
                          ? 'border-cyber-cyan bg-cyber-cyan text-black'
                          : 'border-surface-500 bg-surface-900 text-transparent hover:border-cyber-cyan/70'
                      } disabled:cursor-not-allowed`}
                    >
                      <Check size={13} strokeWidth={3} />
                    </button>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="font-medium leading-snug text-white">
                      {index + 1}. {item.localized_name || item.name}
                    </p>
                    {item.localized_name && item.localized_name !== item.name && (
                      <p className="mt-1 text-[10px] leading-snug text-surface-500">
                        原名：{item.name}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                      <span className="text-cyber-purple">{item.source_label || item.source}</span>
                      <span className={`rounded border px-1.5 py-0.5 ${
                        item.detail_verified
                          ? 'border-cyber-green/25 bg-cyber-green/10 text-cyber-green'
                          : 'border-surface-600 bg-surface-800 text-surface-500'
                      }`}>
                        {item.detail_verified
                          ? '详情已核验'
                          : item.verification_status === 'blocked'
                            ? '详情核验受阻'
                            : '待详情核验'}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="leading-relaxed text-surface-300">{item.content}</p>
                    <p className="mt-2 border-l-2 border-cyber-cyan/25 pl-2 text-[10px] leading-relaxed text-surface-500">
                      <span className="text-surface-400">推荐依据：</span>
                      {item.recommendation_reason || '来自本轮搜索候选，建议结合功能与风险信息判断'}
                    </p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="font-mono text-[11px] text-surface-300">{item.version}</p>
                    <p className="mt-1.5 font-mono text-[10px] text-surface-500">{item.updated_at}</p>
                    <p className="mt-1 text-[10px] text-surface-500">{item.freshness}</p>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <span className={`inline-flex max-w-full rounded border px-2 py-1 text-[10px] leading-relaxed ${conflictTone[item.conflict_status] || conflictTone.unknown}`}>
                      {item.conflict}
                    </span>
                    <div className="mt-2">
                      {item.dependencies?.length
                        ? (
                          <>
                            <p className="mb-1 text-[10px] text-surface-500">依赖</p>
                            <div className="flex flex-wrap gap-1">{item.dependencies.map(dep => (
                              <span key={dep} className="rounded bg-cyber-purple/10 px-1.5 py-0.5 text-[10px] text-cyber-purple">{dep}</span>
                            ))}</div>
                          </>
                        )
                        : (
                          <span className="text-[10px] text-surface-500">
                            {item.dependency_status === 'none_verified'
                              ? '详情中未发现明确依赖'
                              : '依赖信息待详情核验'}
                          </span>
                        )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3 border-t border-surface-700/80 px-4 py-3">
        <div>
          <p className="mb-2 text-[10px] text-surface-500">“详情已核验”只代表页面元数据已取得，不等于安装包兼容性已通过。</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={disabled || locked} onClick={() => update(selectableKeys)} className="btn-ghost px-2.5 py-1.5 text-[11px]">全选可安装项</button>
            <button type="button" disabled={disabled || locked} onClick={() => update([])} className="btn-ghost px-2.5 py-1.5 text-[11px]">清空</button>
            <button type="button" disabled={disabled || locked} onClick={() => update(defaults)} className="btn-ghost flex items-center gap-1 px-2.5 py-1.5 text-[11px]">
              <RotateCcw size={11} /> 恢复智能预选
            </button>
          </div>
        </div>
        <button
          type="button"
          disabled={disabled || locked || selectedItems.length === 0}
          onClick={() => onSubmit?.(selectedItems)}
          className={`rounded-md px-4 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            isConfirmation
              ? 'bg-cyber-yellow/90 text-black hover:bg-cyber-yellow'
              : 'bg-cyber-cyan/90 text-black hover:bg-cyber-cyan'
          }`}
        >
          {phase === 'executing'
            ? '正在执行安装流程…'
            : phase === 'completed'
              ? '安装流程已提交'
              : isConfirmation
                ? `确认下载并安装 ${selectedItems.length} 项`
            : `生成安装计划（${selectedItems.length} 项）`}
        </button>
      </div>
    </section>
  )
}

export function applyEditionDefaultBackground() {
  document.body.classList.remove('has-bg', 'default-bg')
  document.body.style.backgroundImage = ''
}

export function SettingsEditionPanel({ toast }) {
  const initial = readVisualPreferences()
  const [controls, setControls] = useState(initial.controls)
  const [visual, setVisual] = useState(initial.visual)
  const [lighting, setLighting] = useState(initial.lighting)
  const [soundEditing, setSoundEditing] = useState(false)
  const [selectedSound, setSelectedSound] = useState('reply-complete')
  const [selectedVolume, setSelectedVolume] = useState(() => getFeedbackSoundVolume('reply-complete'))
  const [replySoundEnabled, setReplySoundEnabled] = useState(() => {
    try { return localStorage.getItem('modagent-reply-sound-enabled') !== 'false' } catch (_) { return true }
  })
  const [windowsNotification, setWindowsNotification] = useState(() => {
    try { return localStorage.getItem('modagent-reply-windows-notification') === 'true' } catch (_) { return false }
  })

  const save = (key, value, setter, label) => {
    setter(value)
    saveVisualPreference(key, value)
    emitFeedback('notice', { source: key, value })
    toast(label)
  }

  return (
    <>
      <div className="theme-appearance-card card-cyber space-y-3">
        <div className="flex items-center gap-2 mb-1">
          <Palette size={14} className="text-cyber-cyan" />
          <span className="text-sm font-medium">界面主题</span>
        </div>
        <p className="text-xs text-surface-500">订阅版主题、氛围打光与科技核心控件。</p>
        <label className="text-xs text-surface-500 block">主体配色</label>
        <select className="input-cyber" value={visual} onChange={event => {
          const value = event.target.value
          save('visual', value, setVisual, `视觉主题：${VISUAL_THEMES.find(item => item.value === value)?.label || value}`)
        }}>
          {VISUAL_THEMES.map(item => <option key={item.value} value={item.value}>{item.label} · {item.note}</option>)}
        </select>
        <label className="text-xs text-surface-500 block">氛围打光</label>
        <select className="input-cyber" value={lighting} onChange={event => {
          const value = event.target.value
          save('lighting', value, setLighting, `氛围打光：${LIGHTING_MODES.find(item => item.value === value)?.label || value}`)
        }}>
          {LIGHTING_MODES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <label className="text-xs text-surface-500 block">控件外壳</label>
        <select className="input-cyber" value={controls} onChange={event => {
          const value = event.target.value
          const labels = {
            classic: '已恢复经典控件',
            'technology-core': '已启用科技核心完整主题',
            'minimal-tech': '已启用现代简约科技主题',
          }
          save('controls', value, setControls, labels[value] || '控件主题已更新')
        }}>
          <option value="classic">经典界面</option>
          <option value="technology-core">科技核心</option>
          <option value="minimal-tech">现代简约科技</option>
        </select>
      </div>

      <div className="feedback-calibration-card card-cyber space-y-3">
        <div className="flex items-center gap-2 mb-1">
          <Volume2 size={14} className="text-cyber-cyan" />
          <span className="text-sm font-medium">反馈校准</span>
          <button
            type="button"
            data-feedback-no-press="true"
            className={`ml-auto btn-ghost px-2 py-1 text-[11px] ${soundEditing ? 'text-cyber-cyan' : ''}`}
            onClick={() => setSoundEditing(value => !value)}
          >
            <Pencil size={11} className="inline mr-1" />
            {soundEditing ? '完成编辑' : '编辑音量'}
          </button>
        </div>
        <p className="text-xs text-surface-500">
          {soundEditing ? '选择一种反馈，再用下方滑块单独调整它的音量。' : '点击可试听中枢动效与音效，不执行实际操作。'}
        </p>
        <div className="grid grid-cols-1 gap-2 rounded-lg border border-surface-600/70 bg-surface-900/45 p-3">
          <label className="flex cursor-pointer items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2"><Bell size={13} className="text-cyber-cyan" />每次回复完成播放轻提示</span>
            <input
              type="checkbox"
              checked={replySoundEnabled}
              onChange={event => {
                const checked = event.target.checked
                setReplySoundEnabled(checked)
                try { localStorage.setItem('modagent-reply-sound-enabled', String(checked)) } catch (_) {}
                if (checked) emitFeedback('reply-complete', { source: 'settings-enable' })
              }}
            />
          </label>
          <label className="flex cursor-pointer items-center justify-between gap-3 text-xs">
            <span>
              <span className="block">离开窗口时显示 Windows 通知</span>
              <span className="mt-0.5 block text-[10px] text-surface-500">点击通知可立即返回 ModAgent</span>
            </span>
            <input
              type="checkbox"
              checked={windowsNotification}
              onChange={event => {
                const checked = event.target.checked
                setWindowsNotification(checked)
                try { localStorage.setItem('modagent-reply-windows-notification', String(checked)) } catch (_) {}
              }}
            />
          </label>
        </div>
        {soundEditing && (
          <div className="rounded-lg border border-cyber-cyan/25 bg-cyber-cyan/[0.045] p-3">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span>
                正在调整：{FEEDBACK_TESTS.find(item => item.type === selectedSound)?.label || selectedSound}
              </span>
              <span className="font-mono text-cyber-cyan">{Math.round(selectedVolume * 100)}%</span>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              value={Math.round(selectedVolume * 100)}
              aria-label="当前音效音量"
              className="w-full accent-cyan-400"
              onChange={event => {
                const value = Number(event.target.value) / 100
                setSelectedVolume(value)
                setFeedbackSoundVolume(selectedSound, value)
              }}
              onMouseUp={() => emitFeedback(selectedSound, { source: 'settings-volume-preview' })}
              onTouchEnd={() => emitFeedback(selectedSound, { source: 'settings-volume-preview' })}
            />
            <div className="mt-2 flex justify-between">
              <button
                type="button"
                data-feedback-no-press="true"
                className="btn-ghost px-2 py-1 text-[10px]"
                onClick={() => emitFeedback(selectedSound, { source: 'settings-volume-preview' })}
              >
                试听当前音量
              </button>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-[10px]"
                onClick={() => {
                  resetFeedbackSoundVolumes()
                  setSelectedVolume(1)
                  toast('所有反馈音量已恢复默认值')
                }}
              >
                恢复全部默认
              </button>
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          {FEEDBACK_TESTS.map(item => (
            <button
              key={item.type}
              type="button"
              data-feedback-no-press="true"
              className={`btn-ghost text-xs px-2 py-2 text-left flex items-center gap-2 ${
                soundEditing && selectedSound === item.type ? 'border-cyber-cyan/60 bg-cyber-cyan/10 text-white' : ''
              }`}
              onClick={() => {
                if (soundEditing) {
                  setSelectedSound(item.type)
                  setSelectedVolume(getFeedbackSoundVolume(item.type))
                  return
                }
                emitFeedback(item.type, {
                  source: 'settings-test',
                  ...(item.count ? { count: item.count } : {}),
                })
              }}
            >
              <span className="text-[9px] font-mono tracking-wider text-cyber-cyan/45">{item.code}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  )
}
