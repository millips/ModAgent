import React from 'react'
import {
  AlertTriangle,
  Check,
  ExternalLink,
  Heart,
  ListChecks,
  RotateCcw,
  ShieldAlert,
  Wrench,
} from 'lucide-react'

const conflictTone = {
  warning: 'border-cyber-yellow/30 bg-cyber-yellow/10 text-cyber-yellow',
  danger: 'border-cyber-red/30 bg-cyber-red/10 text-cyber-red',
  clear: 'border-cyber-green/30 bg-cyber-green/10 text-cyber-green',
  unknown: 'border-surface-600 bg-surface-800 text-surface-400',
}

const resolutionLabels = {
  verify_detail: '立即核验详情',
  open_source: '打开来源页',
  manual_import: '下载后导入',
}

export function RecommendationDecisionTable({
  message,
  onChange,
  onSubmit,
  onResolve,
  disabled = false,
}) {
  if (message?.payload?.kind !== 'recommendation_set') return null
  const payload = message.payload
  const items = Array.isArray(payload.items) ? payload.items : []
  const selected = new Set(payload.selected_keys || [])
  const wanted = new Set(payload.wanted_keys || [])
  const requirements = Array.isArray(payload.dependency_requirements)
    ? payload.dependency_requirements : []
  const phase = ['confirm', 'executing', 'completed'].includes(payload.phase)
    ? payload.phase : 'recommendation'
  const isConfirmation = phase !== 'recommendation'
  const locked = phase === 'executing' || phase === 'completed'
  const selectedItems = items.filter(
    item => item.installable !== false && selected.has(item.selection_key)
  )
  const wantedItems = items.filter(
    item => item.installable === false && wanted.has(item.selection_key)
  )
  const selectableKeys = items
    .filter(item => item.installable !== false)
    .map(item => item.selection_key)
  const defaults = items.filter(item => item.default_selected).map(item => item.selection_key)
  const sourceCount = new Set(items.map(item => item.source).filter(Boolean)).size
  const verifiedCount = items.filter(item => item.detail_verified).length
  const unavailableCount = items.filter(item => item.installable === false).length
  const unresolvedRequirements = requirements.filter(
    requirement => ['unresolved', 'needs_resolution'].includes(requirement.status)
  )
  const verificationCoverage = items.length
    ? Math.round((verifiedCount / items.length) * 100)
    : 100

  const update = (keys, wantedKeys = [...wanted]) => {
    onChange?.([...new Set(keys)], [...new Set(wantedKeys)])
  }

  const selectedTargetNames = keys => {
    const keySet = new Set(keys)
    return new Set(items
      .filter(item => !item.is_prerequisite && keySet.has(item.selection_key))
      .flatMap(item => [item.name, item.localized_name].filter(Boolean)))
  }

  const addRequiredDependencies = keys => {
    const next = new Set(keys)
    const targetNames = selectedTargetNames(next)
    requirements.forEach(requirement => {
      if (
        requirement.status === 'ready'
        && requirement.matched_selection_key
        && (requirement.required_by || []).some(name => targetNames.has(name))
      ) {
        next.add(requirement.matched_selection_key)
      }
    })
    return [...next]
  }

  const prerequisiteLocked = item => {
    if (!item.is_prerequisite) return false
    const targets = selectedTargetNames(selected)
    return (item.required_by || []).some(name => targets.has(name))
  }

  const toggle = item => {
    if (item.installable === false) {
      const nextWanted = new Set(wanted)
      if (nextWanted.has(item.selection_key)) nextWanted.delete(item.selection_key)
      else nextWanted.add(item.selection_key)
      update([...selected], [...nextWanted])
      return
    }
    if (prerequisiteLocked(item)) return
    const next = new Set(selected)
    if (next.has(item.selection_key)) next.delete(item.selection_key)
    else next.add(item.selection_key)
    update(addRequiredDependencies(next))
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
                  : '智能推荐 · 决策清单'}
          </div>
          <p className="mt-1.5 max-w-3xl text-[11px] leading-relaxed text-surface-500">
            {isConfirmation
              ? '实际安装只处理最终勾选项及核实后的必要依赖；执行前仍会进行下载包与路径检查。'
              : '前置依赖置顶；暂不可安装的候选仍可保留目标，并通过核验、来源页或手动导入继续处理。'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-surface-400">
            <span className="pro-recommendation-stat">{items.length} 个候选</span>
            <span className="pro-recommendation-stat">{sourceCount || 1} 个来源</span>
            <span className="pro-recommendation-stat">{verifiedCount} 项详情已核验</span>
            <span className={`pro-recommendation-stat ${
              verificationCoverage < 95 ? 'is-warning' : ''
            }`}>核验覆盖 {verificationCoverage}%</span>
            {unavailableCount > 0 && (
              <span className="pro-recommendation-stat is-warning">
                {unavailableCount} 项需要处理后安装
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="rounded-full border border-cyber-cyan/20 bg-cyber-cyan/10 px-3 py-1.5 text-[11px] font-medium text-cyber-cyan">
            已选 {selectedItems.length} / {items.length}
          </div>
          {wantedItems.length > 0 && (
            <p className="mt-1.5 text-[10px] text-cyber-yellow">
              已保留 {wantedItems.length} 个待处理目标
            </p>
          )}
        </div>
      </div>

      {requirements.length > 0 && (
        <div className="border-b border-surface-700/80 bg-cyber-purple/[0.06] px-5 py-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-white">
            <Wrench size={14} className="text-cyber-purple" />
            前置 / 必要依赖（优先处理）
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {requirements.map(requirement => (
              <div
                key={`${requirement.name}:${(requirement.required_by || []).join('|')}`}
                className={`rounded border px-3 py-2 text-[10px] ${
                  ['ready', 'satisfied_installed', 'satisfied_local'].includes(requirement.status)
                    ? 'border-cyber-green/25 bg-cyber-green/[0.06]'
                    : 'border-cyber-yellow/25 bg-cyber-yellow/[0.06]'
                }`}
              >
                <p className="font-medium text-white">
                  <span className="mr-1.5 rounded bg-cyber-purple/15 px-1.5 py-0.5 text-cyber-purple">
                    前置依赖
                  </span>
                  {requirement.name}
                </p>
                <p className="mt-1 text-surface-400">
                  被 {(requirement.required_by || []).join('、') || '目标 Mod'} 需要
                </p>
                <p className={
                  ['ready', 'satisfied_installed', 'satisfied_local'].includes(requirement.status)
                    ? 'text-cyber-green' : 'text-cyber-yellow'
                }>
                  {requirement.status === 'ready'
                    ? '已匹配可安装候选，将排在目标 Mod 之前'
                    : requirement.status === 'satisfied_installed'
                      ? '本机已经安装，安装计划不会重复下载'
                      : requirement.status === 'satisfied_local'
                        ? '当前加载器环境已经满足'
                    : requirement.status === 'needs_resolution'
                      ? '已匹配候选，但需要先完成核验或下载处理'
                      : '尚未匹配明确来源；该目标不能进入安装确认'}
                </p>
              </div>
            ))}
          </div>
          {unresolvedRequirements.length > 0 && (
            <p className="mt-2 flex items-center gap-1 text-[10px] text-cyber-yellow">
              <AlertTriangle size={11} />
              未解决的必要依赖不会被静默跳过；执行安装前必须核实或明确转为手动处理。
            </p>
          )}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="pro-recommendation-table w-full min-w-[1040px] table-fixed text-left text-xs">
          <thead className="bg-surface-800/90 text-[10px] uppercase tracking-wider text-surface-500">
            <tr>
              <th className="w-16 px-3 py-3 text-center">选择</th>
              <th className="w-56 px-3 py-3">Mod</th>
              <th className="w-[23rem] px-3 py-3">功能与推荐依据</th>
              <th className="w-36 px-3 py-3">版本 / 活跃度</th>
              <th className="w-64 px-3 py-3">兼容风险与依赖</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-700/70">
            {items.map((item, index) => {
              const unavailable = item.installable === false
              const checked = unavailable
                ? wanted.has(item.selection_key)
                : selected.has(item.selection_key)
              const dependencyLocked = prerequisiteLocked(item)
              return (
                <tr
                  key={item.selection_key}
                  className={`${checked ? 'bg-cyber-cyan/[0.045]' : 'bg-transparent'} hover:bg-white/[0.025]`}
                >
                  <td className="px-3 py-3 text-center align-top">
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      aria-label={unavailable ? `保留目标 ${item.name}` : `选择 ${item.name}`}
                      disabled={disabled || locked || dependencyLocked}
                      onClick={() => toggle(item)}
                      className={`mx-auto flex h-5 w-5 items-center justify-center rounded border transition-colors ${
                        checked
                          ? unavailable
                            ? 'border-cyber-yellow bg-cyber-yellow text-black'
                            : 'border-cyber-cyan bg-cyber-cyan text-black'
                          : 'border-surface-500 bg-surface-900 text-transparent hover:border-cyber-cyan/70'
                      } disabled:cursor-not-allowed`}
                    >
                      {unavailable ? <Heart size={12} fill={checked ? 'currentColor' : 'none'} /> : <Check size={13} strokeWidth={3} />}
                    </button>
                    {unavailable && (
                      <p className="mt-1 text-[9px] text-cyber-yellow">保留目标</p>
                    )}
                    {dependencyLocked && (
                      <p className="mt-1 text-[9px] text-cyber-purple">必要依赖</p>
                    )}
                  </td>
                  <td className="px-3 py-3 align-top">
                    {item.is_prerequisite && (
                      <span className="mb-1.5 inline-flex rounded bg-cyber-purple/15 px-1.5 py-0.5 text-[9px] text-cyber-purple">
                        前置依赖 · 已置顶
                      </span>
                    )}
                    {item.installed_match_kind === 'functional_alternative' && (
                      <span className="mb-1.5 inline-flex rounded border border-cyber-yellow/25 bg-cyber-yellow/10 px-1.5 py-0.5 text-[9px] text-cyber-yellow">
                        已安装同类替代方案
                      </span>
                    )}
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
                    {unavailable && (
                      <div className="mt-2 rounded border border-cyber-yellow/20 bg-cyber-yellow/[0.05] p-2">
                        <p className="text-[10px] leading-relaxed text-cyber-yellow">
                          {item.resolution_title || '当前需要处理后才能安装'}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {(item.resolution_actions || [])
                            .filter(action => action !== 'keep')
                            .map(action => (
                              <button
                                key={action}
                                type="button"
                                disabled={disabled || locked || (action === 'open_source' && !item.url)}
                                onClick={() => onResolve?.(item, action)}
                                className="btn-ghost flex items-center gap-1 px-2 py-1 text-[10px]"
                              >
                                {action === 'open_source' && <ExternalLink size={10} />}
                                {resolutionLabels[action] || action}
                              </button>
                            ))}
                        </div>
                      </div>
                    )}
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
                    {item.required_loader && (
                      <div className={`mt-2 rounded border px-2 py-1.5 text-[10px] ${
                        item.loader_compatible === true
                          ? 'border-cyber-green/25 bg-cyber-green/[0.06] text-cyber-green'
                          : 'border-cyber-red/25 bg-cyber-red/[0.06] text-cyber-red'
                      }`}>
                        必需加载器：{item.required_loader}
                        {item.active_loader
                          ? ` · 当前：${item.active_loader}`
                          : ' · 当前加载器待核验'}
                      </div>
                    )}
                    <div className="mt-2">
                      {item.dependencies?.length
                        ? (
                          <>
                            <p className="mb-1 text-[10px] text-surface-500">必要依赖</p>
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
                    {item.required_by?.length > 0 && (
                      <p className="mt-2 text-[10px] text-cyber-purple">
                        被 {item.required_by.join('、')} 需要
                      </p>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3 border-t border-surface-700/80 px-4 py-3">
        <div>
          <p className="mb-2 text-[10px] text-surface-500">
            “详情已核验”只代表页面元数据已取得；待处理目标会跨会话保留，但不会绕过安全门禁。
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={disabled || locked} onClick={() => update(addRequiredDependencies(selectableKeys))} className="btn-ghost px-2.5 py-1.5 text-[11px]">全选可安装项</button>
            <button type="button" disabled={disabled || locked} onClick={() => update([], [])} className="btn-ghost px-2.5 py-1.5 text-[11px]">清空</button>
            <button type="button" disabled={disabled || locked} onClick={() => update(addRequiredDependencies(defaults), [])} className="btn-ghost flex items-center gap-1 px-2.5 py-1.5 text-[11px]">
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
