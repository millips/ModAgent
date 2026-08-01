import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardCheck, ExternalLink, FileJson, FolderGit2, RefreshCw, ShieldCheck, XCircle } from 'lucide-react'

const REPO = 'millips/ModAgent-Share'
const REVIEW_LABELS = new Set(['censoring', 'reviewing', '审核中', '审查'])
const LOCAL_REPO_KEY = 'modagent-share-reviewer-repository-v1'

function openExternal(url) {
  if (!url) return
  window.modagent?.openExternal?.(url) || window.open(url, '_blank', 'noopener,noreferrer')
}

function readRepository() {
  try { return String(window.localStorage.getItem(LOCAL_REPO_KEY) || '') } catch (_) { return '' }
}

function issueLabels(issue) {
  return (issue?.labels || []).map(item => String(item?.name || item || '').trim()).filter(Boolean)
}

function isPending(issue) {
  const labels = issueLabels(issue).map(item => item.toLowerCase())
  return labels.some(label => REVIEW_LABELS.has(label))
}

function issueSubmissionId(issue) {
  return String(issue?.body || '').match(/\bms-\d{8}-[A-Z0-9]{8}\b/i)?.[0] || '未找到投稿编号'
}

function issueGame(issue) {
  const body = String(issue?.body || '')
  const match = body.match(/(?:游戏和游戏站点|game and game slug)\s*\n+([^\n#]{1,160})/i)
  return match?.[1]?.trim() || '待从 JSON / Issue 核验'
}

function issueSourceCount(issue) {
  return (String(issue?.body || '').match(/https:\/\//g) || []).length
}

function dateLabel(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function manifestSummary(manifest) {
  if (!manifest || typeof manifest !== 'object') return null
  const mods = Array.isArray(manifest.mods) ? manifest.mods : []
  const sourceTypes = [...new Set(mods.map(item => item?.source?.type).filter(Boolean))]
  const deps = mods.reduce((total, item) => total + (Array.isArray(item?.dependencies) ? item.dependencies.length : 0), 0)
  return {
    title: String(manifest.title || ''),
    game: manifest.game || {},
    modCount: mods.length,
    dependencyCount: deps,
    sourceTypes,
    sourceEvidence: String(manifest.source_evidence || manifest.author_note || ''),
    compatibility: String(manifest.compatibility || manifest.warning || ''),
    mods,
  }
}

function dependencyIdentity(value) {
  const raw = String(value || '').trim().toLowerCase()
  if (!raw) return ''
  const withoutVersion = raw.replace(/[-_.\s]+v?\d+(?:\.\d+){1,4}(?:[-+][a-z0-9.-]+)?$/i, '')
  return withoutVersion.replace(/[^a-z0-9]+/g, '')
}

function dependencyVersion(value) {
  const match = String(value || '').match(/(?:^|[-_.\s])v?(\d+(?:\.\d+){1,4})(?:[-+][a-z0-9.-]+)?$/i)
  return match ? match[1].split('.').map(part => Number(part)) : []
}

function versionAtLeast(actual, wanted) {
  if (!wanted.length || !actual.length) return true
  const length = Math.max(actual.length, wanted.length)
  for (let index = 0; index < length; index += 1) {
    const left = actual[index] || 0
    const right = wanted[index] || 0
    if (left !== right) return left > right
  }
  return true
}

function isBaseDependency(value) {
  return /^(?:bepinex|melonloader|smapi)[-_]/i.test(String(value || '').trim())
}

function sourceIdentity(item) {
  const source = item?.source || {}
  return dependencyIdentity(source.key || '') || dependencyIdentity(item?.name || '')
}

function machineChecks(issue, manifest) {
  if (!manifest || typeof manifest !== 'object') return []
  const mods = Array.isArray(manifest.mods) ? manifest.mods : []
  const actualSubmissionId = String(manifest.submission?.id || '')
  const expectedSubmissionId = String(issue?.body || '').match(/\bms-\d{8}-[A-Z0-9]{8}\b/i)?.[0] || ''
  const localIds = new Set(mods.map(item => String(item?.local_id || '')).filter(Boolean))
  const badSources = mods.filter(item => {
    try { return !item?.source?.type || new URL(String(item?.source?.url || '')).protocol !== 'https:' } catch (_) { return true }
  })
  const packageMods = mods.map(item => ({
    item,
    identity: sourceIdentity(item),
    version: dependencyVersion(item?.source?.version || item?.version),
  })).filter(item => item.identity)
  const invalidDependencies = []
  const includedDependencies = []
  const baseDependencies = []
  const externalDependencies = []
  mods.forEach(item => (item?.dependencies || []).forEach(raw => {
    const dependency = String(raw || '').trim()
    if (!dependency) { invalidDependencies.push('(空依赖)'); return }
    if (localIds.has(dependency)) { includedDependencies.push(dependency); return }
    const identity = dependencyIdentity(dependency)
    const candidate = packageMods.find(entry => entry.identity === identity)
    if (candidate && versionAtLeast(candidate.version, dependencyVersion(dependency))) {
      includedDependencies.push(dependency)
    } else if (isBaseDependency(dependency)) {
      baseDependencies.push(dependency)
    } else {
      externalDependencies.push(dependency)
    }
  }))
  const forbidden = []
  const walk = (value, path = 'root') => {
    if (value && typeof value === 'object') Object.entries(value).forEach(([key, child]) => {
      const allowedPrivacyFlag = path === 'root.privacy' && key === 'api_keys_included' && child === false
      if (/(api[_-]?key|token|password|secret|cookie|authorization)/i.test(key) && !allowedPrivacyFlag) forbidden.push(`${path}.${key}`)
      walk(child, `${path}.${key}`)
    })
  }
  walk(manifest)
  return [
    { label: '投稿编号与 Issue', ok: Boolean(expectedSubmissionId && actualSubmissionId && expectedSubmissionId.toLowerCase() === actualSubmissionId.toLowerCase()), detail: expectedSubmissionId ? `${actualSubmissionId || '缺失'} ↔ ${expectedSubmissionId}` : 'Issue 正文未找到投稿编号' },
    { label: '格式与游戏信息', ok: manifest.schema === 'modagent-share/v1' && manifest.kind === 'player_share' && Boolean(manifest.game?.name && manifest.game?.slug), detail: `${manifest.schema || '无 schema'} · ${manifest.game?.name || '未填写游戏'}` },
    { label: '上游来源', ok: badSources.length === 0 && mods.length > 0, detail: badSources.length ? `${badSources.length} 个 Mod 缺少公开 HTTPS 来源` : `${mods.length} 个 Mod 均含来源类型与 HTTPS 页面` },
    {
      label: '前置依赖分流',
      ok: invalidDependencies.length === 0,
      warning: baseDependencies.length > 0 || externalDependencies.length > 0,
      detail: invalidDependencies.length
        ? `存在无效依赖字段：${invalidDependencies.slice(0, 3).join('、')}`
        : `合集已带 ${[...new Set(includedDependencies)].length} 项；用户主机需核验基础环境 ${[...new Set(baseDependencies)].length} 项${externalDependencies.length ? `、外部前置 ${[...new Set(externalDependencies)].length} 项` : ''}`,
    },
    { label: '隐私与密钥字段', ok: forbidden.length === 0, detail: forbidden.length ? `发现敏感字段：${forbidden.slice(0, 2).join('、')}` : '未发现 API Key、token、密码或本机路径字段' },
  ]
}

export default function ReviewerConsole({ toast }) {
  const [repository, setRepository] = useState(readRepository)
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [selected, setSelected] = useState(null)
  const [submission, setSubmission] = useState(null)
  const [preview, setPreview] = useState(null)
  const [actionBusy, setActionBusy] = useState(false)

  const pending = useMemo(() => issues.filter(isPending), [issues])
  const summary = useMemo(() => manifestSummary(submission?.manifest), [submission])
  const checks = useMemo(() => machineChecks(selected, submission?.manifest), [selected, submission])

  const loadIssues = async () => {
    setLoading(true)
    setLoadError('')
    try {
      const result = await window.modagent?.loadReviewerIssues?.()
      if (!result?.ok) throw new Error(result?.error || '无法读取 GitHub 审核队列')
      const rows = Array.isArray(result.issues) ? result.issues : []
      setIssues(rows)
      if (selected) setSelected(current => rows.find(item => item.number === current?.number) || current)
    } catch (error) {
      setLoadError(error?.message || '无法读取 GitHub 审核队列')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadIssues() }, [])

  const chooseRepository = async () => {
    const result = await window.modagent?.selectReviewerRepository?.()
    if (!result) return
    if (result.error) { toast(result.error, 'error'); return }
    window.localStorage.setItem(LOCAL_REPO_KEY, result.path)
    setRepository(result.path)
    toast('已关联本机 ModAgent-Share 官方仓库。')
  }

  const chooseSubmission = async () => {
    const result = await window.modagent?.selectReviewerSubmission?.()
    if (!result) return
    if (result.error) { toast(result.error, 'error'); return }
    if (!result.manifest || result.manifest.kind !== 'player_share') {
      toast('请选择 ModAgent 导出的 player_share 投稿 JSON。', 'error')
      return
    }
    setSubmission(result)
    setPreview(null)
    toast(`已读取投稿 JSON：${Array.isArray(result.manifest.mods) ? result.manifest.mods.length : 0} 个 Mod。`)
    await runPublisher(false, result)
  }

  const runPublisher = async (publish, selectedSubmission = submission) => {
    if (!selected || !repository || !selectedSubmission?.path) {
      toast('请先选择待审核 Issue、本机官方仓库和投稿 JSON。', 'error')
      return
    }
    const localChecks = machineChecks(selected, selectedSubmission.manifest)
    const failed = localChecks.filter(item => !item.ok)
    if (failed.length) {
      const output = `机器核验未通过：\n${failed.map(item => `- ${item.label}：${item.detail}`).join('\n')}\n\n未运行入库工具，也未写入任何官方文件。`
      setPreview({ ok: false, output })
      toast('机器核验发现阻止项，未生成入库草案。', 'error')
      return
    }
    if (publish && !window.confirm('确认已人工核验来源、前置、兼容性和内容合规，并写入官方仓库？此操作仍不会自动 Git 推送。')) return
    setActionBusy(true)
    try {
      const result = await window.modagent?.reviewerPublishCollection?.({
        repository,
        submissionPath: selectedSubmission.path,
        issueUrl: selected.html_url,
        publish,
      })
      if (!result?.ok) throw new Error(result?.output || result?.error || '审核工具执行失败')
      setPreview(result)
      toast(publish ? '官方 JSON 与索引已写入。请检查 Git diff 后提交推送。' : '预览通过：已生成候选六码，尚未写入仓库。')
    } catch (error) {
      toast(error?.message || '审核工具执行失败', 'error')
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-5 md:p-7 space-y-5">
      <section className="rounded-2xl border border-cyber-cyan/20 bg-surface-800/75 p-5 shadow-[0_0_40px_rgba(0,212,255,.06)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-cyber-cyan text-xs tracking-[.22em] mb-2">P SHARE / OFFICIAL REVIEW</div>
            <h2 className="text-2xl font-semibold text-white flex items-center gap-2"><ShieldCheck className="text-cyber-cyan" size={23} /> 官方审核台</h2>
            <p className="text-sm text-surface-400 mt-2">读取 GitHub 待审核投稿；审核员核验后才可生成官方六码、清单与索引。本页不向普通投稿者开放入库能力。</p>
          </div>
          <div className="rounded-xl bg-surface-900/70 px-4 py-3 text-right"><div className="text-xl font-semibold text-white">{pending.length}</div><div className="text-xs text-surface-500">待审核</div></div>
        </div>
      </section>

      <section className="rounded-xl border border-surface-600 bg-surface-800/65 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <FolderGit2 size={16} className="text-cyber-cyan" />
          <div className="min-w-0 flex-1"><div className="text-xs text-surface-500">本机官方仓库（仅用于审核员写入，普通用户不需要）</div><div className="truncate text-sm text-surface-200">{repository || '尚未关联'}</div></div>
          <button className="btn-ghost text-xs" onClick={chooseRepository}>选择官方仓库</button>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(330px,.9fr)_minmax(520px,1.5fr)]">
        <section className="rounded-xl border border-surface-600 bg-surface-800/65 p-4">
          <div className="mb-3 flex items-center justify-between gap-3"><div><h3 className="text-sm font-semibold text-white">待审核投稿</h3><p className="mt-1 text-xs text-surface-500">只显示带 `censoring / 审核中` 标签的开放 Issue。</p></div><button className="btn-ghost p-2" disabled={loading} onClick={loadIssues} title="刷新审核队列"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button></div>
          {loadError && <div className="mb-3 rounded border border-cyber-red/30 bg-cyber-red/5 p-2 text-xs text-cyber-red">读取失败：{loadError}</div>}
          <div className="max-h-[62vh] space-y-2 overflow-y-auto pr-1">
            {pending.length === 0 && !loading && <div className="py-10 text-center text-sm text-surface-500">当前没有待审核投稿。</div>}
            {pending.map(issue => <button key={issue.id} type="button" onClick={() => { setSelected(issue); setSubmission(null); setPreview(null) }} className={`w-full rounded-lg border p-3 text-left transition ${selected?.id === issue.id ? 'border-cyber-cyan/60 bg-cyber-cyan/10' : 'border-surface-600 bg-surface-900/45 hover:border-surface-500'}`}>
              <div className="flex items-start justify-between gap-2"><span className="line-clamp-2 text-sm font-medium text-white">#{issue.number} {issue.title}</span><ClipboardCheck size={15} className="shrink-0 text-amber-300" /></div>
              <div className="mt-2 text-xs text-surface-400">{issueGame(issue)}</div>
              <div className="mt-2 flex flex-wrap gap-1">{issueLabels(issue).map(label => <span key={label} className="rounded-full bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">{label}</span>)}</div>
              <div className="mt-2 text-[11px] text-surface-500">{issueSubmissionId(issue)} · {dateLabel(issue.updated_at)}</div>
            </button>)}
          </div>
        </section>

        <section className="rounded-xl border border-surface-600 bg-surface-800/65 p-5">
          {!selected ? <div className="flex min-h-[420px] flex-col items-center justify-center text-center text-surface-500"><ClipboardCheck size={34} className="mb-3 opacity-50" />从左侧选择一个待审核投稿。</div> : <>
            <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs tracking-[.18em] text-cyber-cyan">REVIEW CASE #{selected.number}</div><h3 className="mt-1 text-xl font-semibold text-white">{selected.title}</h3><p className="mt-1 text-xs text-surface-500">投稿编号：{issueSubmissionId(selected)} · Issue 中发现 {issueSourceCount(selected)} 个链接</p></div><button className="btn-ghost text-xs" onClick={() => openExternal(selected.html_url)}><ExternalLink size={13} /> 打开 GitHub Issue</button></div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-lg bg-surface-900/60 p-3"><div className="text-[11px] text-surface-500">游戏</div><div className="mt-1 text-sm text-surface-200">{issueGame(selected)}</div></div><div className="rounded-lg bg-surface-900/60 p-3"><div className="text-[11px] text-surface-500">当前标签</div><div className="mt-1 text-sm text-amber-200">{issueLabels(selected).join(' / ') || '无'}</div></div><div className="rounded-lg bg-surface-900/60 p-3"><div className="text-[11px] text-surface-500">最后更新</div><div className="mt-1 text-sm text-surface-200">{dateLabel(selected.updated_at)}</div></div></div>

            <div className="mt-4 rounded-xl border border-surface-600 bg-surface-900/45 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-medium text-white">核验投稿 JSON</div><div className="mt-1 text-xs text-surface-500">从 Issue 下载附件后在此选择。工具会比对投稿编号、游戏、每个来源 URL 和依赖闭环。</div></div><button className="btn-ghost text-xs" onClick={chooseSubmission}><FileJson size={13} /> 选择投稿 JSON</button></div>
              {summary && <div className="mt-4 space-y-3 border-t border-surface-700 pt-4"><div className="grid gap-2 sm:grid-cols-4 text-xs"><span className="rounded bg-surface-800 px-2 py-1.5 text-surface-300">游戏：{summary.game.name || summary.game.slug || '未填写'}</span><span className="rounded bg-surface-800 px-2 py-1.5 text-surface-300">Mod：{summary.modCount}</span><span className="rounded bg-surface-800 px-2 py-1.5 text-surface-300">依赖边：{summary.dependencyCount}</span><span className="rounded bg-surface-800 px-2 py-1.5 text-surface-300">来源：{summary.sourceTypes.join(' / ') || '未填写'}</span></div>
                <div className="grid gap-2 sm:grid-cols-2">{checks.map(check => <div key={check.label} className={`rounded border p-2 text-xs ${!check.ok ? 'border-cyber-red/35 bg-cyber-red/5 text-cyber-red' : check.warning ? 'border-amber-400/35 bg-amber-400/5 text-amber-100' : 'border-cyber-green/25 bg-cyber-green/5 text-cyber-green'}`}><div className="font-medium">{!check.ok ? '×' : check.warning ? '!' : '✓'} {check.label}</div><div className="mt-1 opacity-85">{check.detail}</div></div>)}</div>
                <p className="text-sm text-surface-200">{summary.title || '投稿未填写标题'}</p>{summary.compatibility && <p className="rounded border border-amber-400/20 bg-amber-400/5 p-2 text-xs text-amber-100">兼容性 / 警告：{summary.compatibility}</p>}<div className="max-h-36 overflow-y-auto rounded bg-surface-800/50 p-2 text-xs text-surface-400">{summary.mods.map((item, index) => <div key={`${item.local_id}-${index}`} className="py-1 border-b border-surface-700/70 last:border-0"><span className="text-surface-200">{item.localized_name || item.name}</span><span className="ml-2 text-surface-500">{item.source?.type || '未知来源'} · 依赖 {Array.isArray(item.dependencies) ? item.dependencies.length : 0}</span></div>)}</div></div>}
            </div>

            <div className="mt-4 rounded-xl border border-cyber-cyan/25 bg-cyber-cyan/5 p-4"><div className="text-sm font-medium text-white">审核决定</div><p className="mt-1 text-xs leading-relaxed text-surface-400">选择 JSON 后会自动运行机器核验。合集内前置须映射或保留稳定包身份；BepInEx 等基础环境不必列入合集，发布后会在导入用户主机时明确检查并补齐。机器通过后，你只需判断来源页面和版本声明是否真实、合集是否有价值、是否含侵权重传/限制级内容/危险说明；机器不能替代这些内容判断。预览不写入；正式入库后仍需你检查 Git diff 并手动推送。</p><div className="mt-3 flex flex-wrap gap-2"><button className="btn-cyber text-sm" disabled={actionBusy || !repository || !submission} onClick={() => runPublisher(false)}><CheckCircle2 size={14} /> {actionBusy ? '校验中…' : '重新运行机器核验'}</button><button className="btn-ghost text-sm text-cyber-green" disabled={actionBusy || !preview?.ok || !submission} onClick={() => runPublisher(true)}><ShieldCheck size={14} /> 确认写入官方仓库</button><button className="btn-ghost text-sm text-cyber-red" onClick={() => openExternal(selected.html_url)}><XCircle size={14} /> 打开 Issue，退回/拒绝</button></div></div>
            {preview?.output && <pre className="mt-4 max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-surface-600 bg-black/25 p-3 text-xs leading-relaxed text-surface-300">{preview.output}</pre>}
            {preview?.output && <p className="mt-3 flex gap-2 text-xs text-surface-500"><AlertTriangle size={14} className="shrink-0 text-amber-300" />写入成功不等于已发布：检查 Git diff 并推送成功后，再将 GitHub Issue 标为“已发布”并粘贴工具生成的数字码回复。</p>}
          </>}
        </section>
      </div>
    </div>
  )
}
