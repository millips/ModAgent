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

const resolutionLabelsEn = {
  verify_detail: 'Verify details now',
  open_source: 'Open source page',
  manual_import: 'Download and import',
}

export function RecommendationDecisionTable({
  message,
  onChange,
  onSubmit,
  onResolve,
  onResolveWanted,
  disabled = false,
  language = 'zh-CN',
}) {
  const en = language === 'en'
  const [showAllDependencies, setShowAllDependencies] = React.useState(false)
  if (message?.payload?.kind !== 'recommendation_set') return null
  const payload = message.payload
  const items = Array.isArray(payload.items) ? payload.items : []
  const selected = new Set(payload.selected_keys || [])
  const wanted = new Set(payload.wanted_keys || [])
  const selectedVariants = payload.selected_variants || {}
  const requirements = Array.isArray(payload.dependency_requirements)
    ? payload.dependency_requirements : []
  const phase = ['planning', 'confirm', 'executing', 'completed'].includes(payload.phase)
    ? payload.phase : 'recommendation'
  const isConfirmation = phase === 'confirm'
  const locked = phase === 'planning' || phase === 'executing' || phase === 'completed'
  const selectedItems = items
    .filter(item => item.installable !== false && selected.has(item.selection_key))
    .map(item => {
      const variants = Array.isArray(item.variants) ? item.variants : []
      const selectedVariantId = selectedVariants[item.selection_key]
        || item.selected_variant_id
        || item.variant_id
        || (item.file_id && variants.find(variant => String(variant.file_id) === String(item.file_id))?.variant_id)
        || variants.find(variant => variant.is_primary)?.variant_id
        || variants[0]?.variant_id
        || ''
      const variant = variants.find(candidate => candidate.variant_id === selectedVariantId)
        || variants[0]
      return variant
        ? {
            ...item,
            selected_variant_id: variant.variant_id,
            variant_id: variant.variant_id,
            file_id: variant.file_id,
            file_name: variant.file_name,
            variant_name: variant.name,
            target_slot: variant.target_slot,
            version: variant.version || item.version,
          }
        : item
    })
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
  const activeTargetNames = new Set(items
    .filter(item => (
      !item.is_prerequisite
      && (selected.has(item.selection_key) || wanted.has(item.selection_key))
    ))
    .flatMap(item => [item.name, item.localized_name].filter(Boolean)))
  const visibleRequirements = requirements.filter(
    requirement => (requirement.required_by || []).some(
      name => activeTargetNames.has(name)
    )
  )
  const renderedRequirements = showAllDependencies
    ? visibleRequirements : visibleRequirements.slice(0, 8)
  const unresolvedRequirements = visibleRequirements.filter(
    requirement => ['unresolved', 'needs_resolution'].includes(requirement.status)
  )
  const verificationCoverage = items.length
    ? Math.round((verifiedCount / items.length) * 100)
    : 100

  const update = (
    keys,
    wantedKeys = [...wanted],
    variantSelections = selectedVariants,
  ) => {
    onChange?.(
      [...new Set(keys)],
      [...new Set(wantedKeys)],
      variantSelections,
    )
  }

  const chooseVariant = (item, variantId) => {
    update([...selected], [...wanted], {
      ...selectedVariants,
      [item.selection_key]: variantId,
    })
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
            {phase === 'planning'
              ? (en ? 'Verifying the installation plan · your choices are preserved' : '安装计划核验中 · 已保留你的选择')
              : phase === 'executing'
              ? (en ? 'Installation in progress · choices locked' : '安装流程执行中 · 选择已锁定')
              : phase === 'completed'
                ? (en ? 'Installation submitted' : '安装流程已提交')
                : isConfirmation
                  ? (en ? 'Install confirmation · final selection' : '安装确认 · 最终选择')
                  : (en ? 'Smart recommendations · decision list' : '智能推荐 · 决策清单')}
          </div>
          <p className="mt-1.5 max-w-3xl text-[11px] leading-relaxed text-surface-500">
            {phase === 'planning'
              ? (en ? 'Verifying exact files, prerequisites and conflicts for your selected Mods. When complete, return here to choose variants and confirm.' : '正在核验已选 Mod 的精确文件、前置依赖与冲突；完成后会回到这张卡中选择变体并确认。')
              : isConfirmation
              ? (en ? 'Installation only handles your final selection and verified prerequisites; package and destination checks still run before execution.' : '实际安装只处理最终勾选项及核实后的必要依赖；执行前仍会进行下载包与路径检查。')
              : (en ? 'Choose targets first. This card only lists their direct dependencies; each item is verified when the plan is generated.' : '先选择目标；这里只汇总所选目标的直接依赖，生成计划时再逐项核验，不会把其他候选的依赖混进来。')}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-surface-400">
            <span className="pro-recommendation-stat">{en ? `${items.length} candidates` : `${items.length} 个候选`}</span>
            <span className="pro-recommendation-stat">{en ? `${sourceCount || 1} sources` : `${sourceCount || 1} 个来源`}</span>
            <span className="pro-recommendation-stat">{en ? `${verifiedCount} details verified` : `${verifiedCount} 项详情已核验`}</span>
            <span className={`pro-recommendation-stat ${
              verificationCoverage < 95 ? 'is-warning' : ''
            }`}>{en ? `Details obtained ${verificationCoverage}% (not relevance)` : `详情取得率 ${verificationCoverage}%（非匹配率）`}</span>
            {unavailableCount > 0 && (
              <span className="pro-recommendation-stat is-warning">
                {en ? `${unavailableCount} need action before install` : `${unavailableCount} 项需要处理后安装`}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="rounded-full border border-cyber-cyan/20 bg-cyber-cyan/10 px-3 py-1.5 text-[11px] font-medium text-cyber-cyan">
            {en ? `Selected ${selectedItems.length} / ${items.length}` : `已选 ${selectedItems.length} / ${items.length}`}
          </div>
          {wantedItems.length > 0 && (
            <p className="mt-1.5 text-[10px] text-cyber-yellow">
              {en ? `${wantedItems.length} wanted targets retained` : `已保留 ${wantedItems.length} 个待处理目标`}
            </p>
          )}
        </div>
      </div>

      {visibleRequirements.length > 0 && (
        <div className="border-b border-surface-700/80 bg-cyber-purple/[0.06] px-5 py-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-white">
            <Wrench size={14} className="text-cyber-purple" />
            当前所选目标的前置 / 必要依赖（{visibleRequirements.length} 项）
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {renderedRequirements.map(requirement => (
              <div
                key={`${requirement.name}:${(requirement.required_by || []).join('|')}`}
                className={`rounded border px-3 py-2 text-[10px] ${
                  ['ready', 'planned', 'satisfied_installed', 'satisfied_local'].includes(requirement.status)
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
                {requirement.version_conflict && (
                  <p className="text-cyber-yellow">
                    多个目标声明了不同版本：
                    {(requirement.requested_versions || []).join(' / ')}
                    ；计划阶段将核验可共同满足的版本
                  </p>
                )}
                <p className={
                  ['ready', 'planned', 'satisfied_installed', 'satisfied_local'].includes(requirement.status)
                    ? 'text-cyber-green' : 'text-cyber-yellow'
                }>
                  {requirement.status === 'ready'
                    ? '已匹配可安装候选，将排在目标 Mod 之前'
                    : requirement.status === 'planned'
                      ? '已加入本轮拟安装计划，共享该依赖的候选已重新计算'
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
          {visibleRequirements.length > 8 && (
            <button
              type="button"
              onClick={() => setShowAllDependencies(value => !value)}
              className="btn-ghost mt-2 px-2.5 py-1 text-[10px]"
            >
              {showAllDependencies
                ? '收起依赖'
                : `展开其余 ${visibleRequirements.length - 8} 项`}
            </button>
          )}
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
              <th className="w-16 px-3 py-3 text-center">{en ? 'Select' : '选择'}</th>
              <th className="w-56 px-3 py-3">Mod</th>
              <th className="w-[23rem] px-3 py-3">{en ? 'Function and recommendation evidence' : '功能与推荐依据'}</th>
              <th className="w-36 px-3 py-3">{en ? 'Version / activity' : '版本 / 活跃度'}</th>
              <th className="w-64 px-3 py-3">{en ? 'Compatibility risks and dependencies' : '兼容风险与依赖'}</th>
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
                      aria-label={unavailable ? (en ? `I want ${item.name}` : `我要这个 ${item.name}`) : (en ? `Select ${item.name}` : `选择 ${item.name}`)}
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
                      <p className="mt-1 text-[9px] text-cyber-yellow">{en ? 'I want this' : '我要这个'}</p>
                    )}
                    {!unavailable && !dependencyLocked && (
                      <p className="mt-1 text-[9px] text-cyber-cyan">{en ? 'Install' : '安装'}</p>
                    )}
                    {dependencyLocked && (
                      <p className="mt-1 text-[9px] text-cyber-purple">{en ? 'Required dependency' : '必要依赖'}</p>
                    )}
                  </td>
                  <td className="px-3 py-3 align-top">
                    {item.is_prerequisite && (
                      <span className="mb-1.5 inline-flex rounded bg-cyber-purple/15 px-1.5 py-0.5 text-[9px] text-cyber-purple">
                        {en ? 'Prerequisite · pinned' : '前置依赖 · 已置顶'}
                      </span>
                    )}
                    {item.installed_match_kind === 'functional_alternative' && (
                      <span className="mb-1.5 inline-flex rounded border border-cyber-yellow/25 bg-cyber-yellow/10 px-1.5 py-0.5 text-[9px] text-cyber-yellow">
                        {en ? 'A similar alternative is installed' : '已安装同类替代方案'}
                      </span>
                    )}
                    <p className="font-medium leading-snug text-white">
                      {index + 1}. {item.localized_name || item.name}
                    </p>
                    {item.localized_name && item.localized_name !== item.name && (
                      <p className="mt-1 text-[10px] leading-snug text-surface-500">
                        {en ? 'Original name: ' : '原名：'}{item.name}
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
                          ? (en ? 'Details verified' : '详情已核验')
                          : item.verification_status === 'blocked'
                            ? (en ? 'Detail verification blocked' : '详情核验受阻')
                            : (en ? 'Detail verification pending' : '待详情核验')}
                      </span>
                    </div>
                    {Array.isArray(item.variants) && item.variants.length > 0 && (
                      <div className="mt-2">
                        <label
                          htmlFor={`variant-${item.selection_key}`}
                          className="mb-1 block text-[10px] text-surface-400"
                        >
                          {item.variants.length > 1 ? (en ? 'Install file / variant' : '安装文件 / 变体') : (en ? 'Install file' : '安装文件')}
                        </label>
                        <select
                          id={`variant-${item.selection_key}`}
                          value={
                            selectedVariants[item.selection_key]
                            || item.selected_variant_id
                            || item.variant_id
                            || (item.file_id && item.variants.find(variant => String(variant.file_id) === String(item.file_id))?.variant_id)
                            || item.variants.find(variant => variant.is_primary)?.variant_id
                            || item.variants[0]?.variant_id
                            || ''
                          }
                          disabled={disabled || locked}
                          onChange={event => chooseVariant(item, event.target.value)}
                          className="w-full rounded border border-surface-600 bg-surface-900 px-2 py-1.5 text-[10px] text-surface-200 outline-none focus:border-cyber-cyan disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {item.variants.map(variant => (
                            <option key={variant.variant_id} value={variant.variant_id}>
                              {variant.name}
                              {variant.version ? ` · v${variant.version}` : ''}
                              {variant.is_primary ? (en ? ' · Recommended' : ' · 推荐') : ''}
                            </option>
                          ))}
                        </select>
                        {item.variants.length > 1 && (
                          <p className="mt-1 text-[9px] leading-relaxed text-surface-500">
                            {en ? 'This only records your choice. The exact file is downloaded after the plan is generated.' : '现在只记录选择；生成计划后才会下载该精确文件。'}
                          </p>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 align-top">
                    <p className="leading-relaxed text-surface-300">{item.content}</p>
                    {item.goal_fit && (
                      <div className="mt-2 text-[11px] text-cyber-cyan">
                        <p>{item.goal_fit.status === 'matched'
                          ? (en ? 'Goal match: supported by functional evidence' : '需求匹配：有功能描述支持')
                          : (en ? 'Goal match: unconfirmed; not preselected' : '需求匹配：尚未确认，未预选')}</p>
                        {item.goal_fit.evidence?.map((proof, index) => <p key={index} className="text-surface-400 mt-1">{proof}</p>)}
                        {item.alternative_names?.length > 0 && <p className="mt-1 text-cyber-yellow">
                          {en ? 'Overlapping alternative, not a proven conflict: ' : '功能重叠的替代方案，并非已证实冲突：'}{item.alternative_names.join(' / ')}
                        </p>}
                        <p className="mt-1 text-surface-400">{en
                          ? (item.default_selected ? 'Preselected for evidence coverage; confirm the plan before installing.' : 'Not preselected. Compare function overlap and installation requirements.')
                          : item.selection_reason}</p>
                      </div>
                    )}
                    <p className="mt-2 border-l-2 border-cyber-cyan/25 pl-2 text-[10px] leading-relaxed text-surface-500">
                      <span className="text-surface-400">{en ? 'Source metadata: ' : '来源参考信息：'}</span>
                      {item.recommendation_reason || (en ? 'This is a candidate from the current search; weigh function and risk information.' : '来自本轮搜索候选，建议结合功能与风险信息判断')}
                    </p>
                    {unavailable && (
                      <div className="mt-2 rounded border border-cyber-yellow/20 bg-cyber-yellow/[0.05] p-2">
                        <p className="text-[10px] leading-relaxed text-cyber-yellow">
                          {item.resolution_title || (en ? 'Action is required before installation.' : '当前需要处理后才能安装')}
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
                                {(en ? resolutionLabelsEn : resolutionLabels)[action] || action}
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
                        {en ? 'Required loader: ' : '必需加载器：'}{item.required_loader}
                        {item.active_loader
                          ? (en ? ` · Current: ${item.active_loader}` : ` · 当前：${item.active_loader}`)
                          : (en ? ' · Current loader pending verification' : ' · 当前加载器待核验')}
                      </div>
                    )}
                    <div className="mt-2">
                      {item.dependencies?.length
                        ? (
                          <>
                            <p className="mb-1 text-[10px] text-surface-500">{en ? 'Required dependencies' : '必要依赖'}</p>
                            <div className="flex flex-wrap gap-1">{item.dependencies.map(dep => (
                              <span key={dep} className="rounded bg-cyber-purple/10 px-1.5 py-0.5 text-[10px] text-cyber-purple">{dep}</span>
                            ))}</div>
                          </>
                        )
                        : (
                          <span className="text-[10px] text-surface-500">
                            {item.dependency_status === 'none_verified'
                              ? (en ? 'No explicit dependency found in verified details' : '详情中未发现明确依赖')
                              : (en ? 'Dependency information pending detail verification' : '依赖信息待详情核验')}
                          </span>
                        )}
                    </div>
                    {item.required_by?.length > 0 && (
                      <p className="mt-2 text-[10px] text-cyber-purple">
                        {en ? `Required by ${item.required_by.join(', ')}` : `被 ${item.required_by.join('、')} 需要`}
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
            {en ? '“Details verified” only means page metadata was retrieved. Wanted targets are retained across sessions, but never bypass safety gates.' : '“详情已核验”只代表页面元数据已取得；待处理目标会跨会话保留，但不会绕过安全门禁。'}
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={disabled || locked} onClick={() => update(addRequiredDependencies(selectableKeys))} className="btn-ghost px-2.5 py-1.5 text-[11px]">{en ? 'Select all installable' : '全选可安装项'}</button>
            <button type="button" disabled={disabled || locked} onClick={() => update([], [])} className="btn-ghost px-2.5 py-1.5 text-[11px]">{en ? 'Clear' : '清空'}</button>
            <button type="button" disabled={disabled || locked} onClick={() => update(addRequiredDependencies(defaults), [])} className="btn-ghost flex items-center gap-1 px-2.5 py-1.5 text-[11px]">
              <RotateCcw size={11} /> {en ? 'Restore smart defaults' : '恢复智能预选'}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!isConfirmation && wantedItems.length > 0 && (
            <button
              type="button"
              disabled={disabled || locked}
              onClick={() => onResolveWanted?.(wantedItems)}
              className="rounded-md border border-cyber-yellow/50 bg-cyber-yellow/10 px-4 py-2 text-xs font-medium text-cyber-yellow transition-colors hover:bg-cyber-yellow/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {en ? `Resolve selected requirements (${wantedItems.length})` : `补齐当前需要（${wantedItems.length} 个）`}
            </button>
          )}
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
            {phase === 'planning'
              ? (en ? 'Verifying installation plan…' : '正在核验安装计划…')
              : phase === 'executing'
              ? (en ? 'Installing…' : '正在执行安装流程…')
              : phase === 'completed'
                ? (en ? 'Installation submitted' : '安装流程已提交')
                : isConfirmation
                  ? (en ? `Confirm download and install (${selectedItems.length})` : `确认下载并安装 ${selectedItems.length} 项`)
                  : (en ? `Generate install plan (${selectedItems.length})` : `生成安装计划（${selectedItems.length} 项）`)}
          </button>
        </div>
      </div>
    </section>
  )
}
