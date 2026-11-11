export function sharePrerequisitesPending(preview) {
  return (preview?.summary?.host_dependency_requirements || []).some(item => ![
    'satisfied_base_environment', 'satisfied_installed', 'included_collection',
  ].includes(item.status))
}

export function sharePlanPrompt(request, language) {
  const official = typeof request?.shareId === 'string' ? request.shareId.trim() : ''
  const share = typeof request?.share === 'string' ? request.share.trim() : ''
  if (!official && !share) return ''
  const prerequisiteOnly = request.action === 'prerequisite_plan'
  if (language === 'en') return `${official ? `Read official ModAgent collection ${official}.` : 'Read the ModAgent share below.'} ${prerequisiteOnly
    ? 'Only verify and plan unresolved base-environment or external prerequisites. Check local presence and versions; explain missing components, sources and risks. Require confirmation. Do not install the main Mods or claim all dependencies are resolved.'
    : 'Prepare an installation plan requiring confirmation. Preserve the collection goal; do not search for or recommend extra Mods. List installed items, dependencies, updates, conflicts, risks and planned file changes. Do not install directly.'}${official ? '' : '\n' + share}`
  return `${official ? `请读取官方 ModAgent 合集 ${official}。` : '请导入以下 ModAgent 分享配置。'}${prerequisiteOnly
    ? '只检查并规划未确认的基础环境/外部前置，核验本机是否存在、版本是否满足，说明缺失项、来源和风险，生成需要确认的计划。不得安装主体 Mod，不得声称依赖已全部解决。'
    : '生成需要确认的安装计划，保留合集目标，不得搜索或推荐额外 Mod；列出已安装项、依赖、更新、冲突、风险及计划写入的文件，不要直接安装。'}${official ? '' : '\n' + share}`
}
