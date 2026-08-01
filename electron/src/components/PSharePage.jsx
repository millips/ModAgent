import React, { useMemo, useState } from 'react'
import { CheckCircle2, ChevronRight, CircleDotDashed, ExternalLink, FileText, Filter, RefreshCw, Sparkles, XCircle } from 'lucide-react'
import { usePShareProfile, usePShareSubmissions, updatePShareSubmission } from '../pshare/pShareStore'

const ISSUE_BASE = 'https://github.com/millips/ModAgent-Share/issues/new?template=collection-submission.yml'
const ISSUE_RE = /^https:\/\/github\.com\/millips\/ModAgent-Share\/issues\/(\d+)\/?$/i

const STATUS = {
  draft: { label: '草稿', tone: 'text-surface-400 bg-surface-700/70', icon: FileText },
  submission_opened: { label: '待提交', tone: 'text-cyber-cyan bg-cyber-cyan/10', icon: ChevronRight },
  reviewing: { label: '审核中', tone: 'text-amber-300 bg-amber-400/10', icon: CircleDotDashed },
  needs_changes: { label: '需修改', tone: 'text-orange-300 bg-orange-400/10', icon: RefreshCw },
  rejected: { label: '未通过', tone: 'text-cyber-red bg-cyber-red/10', icon: XCircle },
  published: { label: '已发布', tone: 'text-cyber-green bg-cyber-green/10', icon: CheckCircle2 },
}

function stamp(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function StatusBadge({ status }) {
  const item = STATUS[status] || STATUS.draft
  const Icon = item.icon
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] ${item.tone}`}><Icon size={12} />{item.label}</span>
}

function openExternal(url) {
  if (!url) return
  window.modagent?.openExternal?.(url) || window.open(url, '_blank', 'noopener,noreferrer')
}

async function copySubmissionText(value, toast, label) {
  try {
    await navigator.clipboard.writeText(value)
    toast(`${label}已复制。`)
  } catch (_) {
    toast(`无法复制${label}，请手动选择文本。`, 'error')
  }
}

function resolveStatus(labels = []) {
  const names = labels.map(label => String(label?.name || label).toLowerCase())
  if (names.includes('published') || names.includes('已发布')) return 'published'
  if (names.includes('rejected') || names.includes('已拒绝') || names.includes('未通过')) return 'rejected'
  if (names.includes('needs-changes') || names.includes('需修改')) return 'needs_changes'
  if (names.includes('reviewing') || names.includes('censoring') || names.includes('审核中') || names.includes('审查')) return 'reviewing'
  return 'reviewing'
}

export default function PSharePage({ toast }) {
  const profile = usePShareProfile()
  const submissions = usePShareSubmissions()
  const [gameFilter, setGameFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [detail, setDetail] = useState(null)
  const [issueUrl, setIssueUrl] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [showSubmissionHelper, setShowSubmissionHelper] = useState(false)

  const games = useMemo(() => [...new Set(submissions.map(item => item.game_name).filter(Boolean))].sort(), [submissions])
  const visible = useMemo(() => submissions.filter(item => (
    (gameFilter === 'all' || item.game_name === gameFilter) &&
    (statusFilter === 'all' || item.status === statusFilter)
  )), [submissions, gameFilter, statusFilter])

  const selectDetail = entry => {
    setDetail(entry)
    setIssueUrl(entry.issue_url || '')
    setShowSubmissionHelper(false)
  }
  const saveIssue = () => {
    if (!detail) return
    const match = issueUrl.trim().match(ISSUE_RE)
    if (!match) {
      toast('请粘贴 ModAgent-Share 仓库的 GitHub Issue 链接。', 'error')
      return
    }
    const next = updatePShareSubmission(detail.submission_id, { issue_url: issueUrl.trim(), status: 'reviewing', issue_number: Number(match[1]) })
    setDetail(next)
    toast('已关联投稿，状态标为“审核中”。')
  }
  const linkIssueFromClipboard = async () => {
    if (!detail) return
    const result = await window.modagent?.readSubmissionIssueFromClipboard?.()
    if (!result?.ok || !result.url) {
      toast(result?.error || '无法读取投稿链接。请先在浏览器地址栏复制 GitHub Issue 地址。', 'error')
      return
    }
    const match = result.url.match(ISSUE_RE)
    const next = updatePShareSubmission(detail.submission_id, {
      issue_url: result.url,
      status: 'reviewing',
      issue_number: Number(match?.[1] || 0),
    })
    setIssueUrl(result.url)
    setDetail(next)
    toast('已从剪贴板关联 GitHub 投稿，状态标为“审核中”。')
  }
  const syncIssue = async () => {
    if (!detail?.issue_url) {
      toast('请先关联 GitHub Issue。', 'error')
      return
    }
    const match = detail.issue_url.match(ISSUE_RE)
    if (!match) {
      toast('投稿链接格式无效。', 'error')
      return
    }
    setSyncing(true)
    try {
      const result = await window.modagent?.syncPShareIssue?.(detail.issue_url)
      if (!result?.ok || !result.issue) throw new Error(result?.error || '无法读取 GitHub Issue。')
      const issue = result.issue
      const body = String(issue.body || '')
      if (!body.includes(detail.submission_id)) throw new Error('该 Issue 未包含对应投稿编号')
      const maCode = body.match(/\bma-[a-z0-9][a-z0-9_-]{1,47}-\d{6}\b/i)?.[0] || detail.ma_code || ''
      const next = updatePShareSubmission(detail.submission_id, {
        status: resolveStatus(issue.labels),
        issue_title: issue.title || '',
        ma_code: maCode,
        synced_at: new Date().toISOString(),
      })
      setDetail(next)
      toast('审核状态已同步。')
    } catch (error) {
      toast(`无法同步审核状态：${error.message || '请检查网络或 Issue 链接'}`, 'error')
    } finally {
      setSyncing(false)
    }
  }

  if (!profile) {
    return <div className="h-full flex items-center justify-center text-surface-400">请先在设置中开通 P Share 创作者计划。</div>
  }

  return (
    <div className="h-full overflow-y-auto p-5 md:p-7 space-y-5">
      <section className="rounded-2xl border border-cyber-cyan/20 bg-surface-800/75 p-5 shadow-[0_0_40px_rgba(0,212,255,.06)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-cyber-cyan text-xs tracking-[.22em] mb-2">P SHARE / CREATOR SPACE</div>
            <h2 className="text-2xl font-semibold text-white flex items-center gap-2"><Sparkles className="text-cyber-cyan" size={22} /> 分享者主页</h2>
            <p className="text-sm text-surface-400 mt-2">{profile.display_name || 'P Share 创作者'} · 管理本机导出的投稿，关联 GitHub Issue 后可查看审核状态。</p>
          </div>
          <div className="rounded-xl bg-surface-900/70 px-4 py-3 text-right">
            <div className="text-xl font-semibold text-white">{submissions.length}</div>
            <div className="text-xs text-surface-500">我的投稿</div>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-surface-600 bg-surface-800/65 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Filter size={16} className="text-surface-500" />
          <select value={gameFilter} onChange={event => setGameFilter(event.target.value)} className="input-cyber min-w-40 text-sm">
            <option value="all">全部游戏</option>
            {games.map(game => <option key={game} value={game}>{game}</option>)}
          </select>
          <select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="input-cyber min-w-32 text-sm">
            <option value="all">全部状态</option>
            {Object.entries(STATUS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
          </select>
          <span className="text-xs text-surface-500 ml-auto">显示 {visible.length} / {submissions.length}</span>
        </div>

        {visible.length === 0 ? (
          <div className="py-14 text-center text-surface-500">
            <FileText size={28} className="mx-auto mb-3 opacity-60" />
            还没有符合条件的投稿。请在 Mod 管理中选择已对齐的 Mod 后导出分享配置。
          </div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead className="text-left text-xs text-surface-500 border-b border-surface-600">
                <tr><th className="pb-3 font-medium">标题</th><th className="pb-3 font-medium">游戏</th><th className="pb-3 font-medium">Mod</th><th className="pb-3 font-medium">导出时间</th><th className="pb-3 font-medium">状态</th><th className="pb-3" /></tr>
              </thead>
              <tbody>
                {visible.map(entry => <tr key={entry.submission_id} className="border-b border-surface-700/70 hover:bg-surface-700/30">
                  <td className="py-3 text-white max-w-[280px] truncate">{entry.title || '未命名合集'}</td>
                  <td className="py-3 text-surface-400">{entry.game_name || '未记录'}</td>
                  <td className="py-3 text-surface-300">{entry.mod_count || 0}</td>
                  <td className="py-3 text-surface-500 text-xs">{stamp(entry.created_at)}</td>
                  <td className="py-3"><StatusBadge status={entry.status} /></td>
                  <td className="py-3 text-right"><button type="button" className="btn-ghost text-xs" onClick={() => selectDetail(entry)}>查看详情</button></td>
                </tr>)}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detail && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/65 p-4" role="dialog" aria-modal="true" aria-label="投稿详情">
        <div className="w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl border border-cyber-cyan/20 bg-surface-900 p-5 shadow-2xl">
          <div className="flex items-start justify-between gap-3"><div><div className="text-xs text-cyber-cyan tracking-[.18em]">SUBMISSION DETAIL</div><h3 className="text-lg text-white mt-1">{detail.title || '未命名合集'}</h3></div><button className="btn-ghost" onClick={() => setDetail(null)}>关闭</button></div>
          <div className="grid grid-cols-2 gap-3 mt-5 text-sm"><div className="rounded-lg bg-surface-800 p-3"><div className="text-xs text-surface-500">投稿编号</div><div className="text-surface-200 break-all mt-1">{detail.submission_id}</div></div><div className="rounded-lg bg-surface-800 p-3"><div className="text-xs text-surface-500">当前状态</div><div className="mt-1"><StatusBadge status={detail.status} /></div></div></div>
          <div className="mt-4 text-sm text-surface-300 space-y-2"><p>游戏：{detail.game_name || '未记录'} · Mod 数量：{detail.mod_count || 0}</p>{detail.description && <p>简介：{detail.description}</p>}{detail.warning && <p className="text-amber-200">警告：{detail.warning}</p>}{detail.filename && <p className="text-surface-500 text-xs">文件：{detail.filename}</p>}</div>
          {!detail.issue_url ? <div className="mt-5 rounded-xl border border-surface-600 p-4"><p className="text-sm text-surface-300 mb-3">打开官方投稿页后按辅助填报完成提交；提交成功后，在浏览器地址栏按 Ctrl+L、Ctrl+C，再回到这里一键关联。</p><div className="flex flex-wrap gap-2"><input className="input-cyber min-w-[18rem] flex-1 text-sm" value={issueUrl} onChange={event => setIssueUrl(event.target.value)} placeholder="https://github.com/millips/ModAgent-Share/issues/123" /><button className="btn-ghost text-sm" onClick={saveIssue}>手动关联</button><button className="btn-cyber text-sm" onClick={linkIssueFromClipboard}>从剪贴板关联 Issue</button></div><button className="btn-ghost text-xs mt-3" onClick={() => { setShowSubmissionHelper(true); openExternal(ISSUE_BASE) }}><ExternalLink size={13} /> 打开官方投稿页与辅助填报</button></div> : <div className="mt-5 rounded-xl border border-surface-600 p-4 flex flex-wrap items-center gap-3"><button className="btn-ghost text-sm" onClick={() => openExternal(detail.issue_url)}><ExternalLink size={14} /> 打开 GitHub Issue</button><button className="btn-cyber text-sm" disabled={syncing} onClick={syncIssue}><RefreshCw size={14} className={syncing ? 'animate-spin' : ''} /> {syncing ? '同步中…' : '同步审核状态'}</button>{detail.ma_code && <span className="text-xs text-cyber-green">已发布代码：{detail.ma_code}</span>}</div>}
        </div>
      </div>}
      {showSubmissionHelper && detail && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-label="GitHub 辅助填报">
        <div className="w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl border border-cyber-cyan/35 bg-surface-900 p-5 shadow-2xl">
          <div className="flex items-start justify-between gap-3"><div><div className="text-xs text-cyber-cyan tracking-[.18em]">GITHUB SUBMISSION HELPER</div><h3 className="text-lg text-white mt-1">辅助填报 · {detail.title || '未命名合集'}</h3><p className="text-xs text-surface-400 mt-1">GitHub 官方表单已在浏览器打开；此窗口会保留，方便逐项复制。</p></div><button className="btn-ghost" onClick={() => setShowSubmissionHelper(false)}>关闭</button></div>
          <div className="mt-5 rounded-xl border border-cyber-cyan/20 bg-surface-800/70 p-4 text-sm text-surface-300">
            <div className="text-xs tracking-[.14em] text-cyber-cyan">提交步骤</div>
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              <li>在浏览器中的 GitHub 表单填写标题与游戏名。</li>
              <li>把本次导出的 JSON 拖入“JSON 清单或拉取请求 URL”字段；下方会得到附件链接。</li>
              <li>按顺序复制本窗口的“来源与依赖说明”和“兼容性说明”，勾选两项承诺后创建 Issue。</li>
              <li>创建成功后，浏览器地址栏按 <b>Ctrl+L</b>、<b>Ctrl+C</b> 复制 Issue 地址。</li>
              <li>回到这里点击底部“从剪贴板关联 Issue”。关联后可在“我的分享”查看审核状态。</li>
            </ol>
          </div>
          <div className="mt-5 space-y-4 text-sm">
            <div><div className="mb-1 text-xs text-surface-500">标题</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-sm" value={detail.title || ''} /><button className="btn-ghost text-xs" onClick={() => copySubmissionText(detail.title || '', toast, '标题')}>复制</button></div></div>
            <div><div className="mb-1 text-xs text-surface-500">游戏和游戏启动器</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-sm" value={detail.game_name || detail.game_slug || ''} /><button className="btn-ghost text-xs" onClick={() => copySubmissionText(detail.game_name || detail.game_slug || '', toast, '游戏信息')}>复制</button></div></div>
            <div><div className="mb-1 text-xs text-surface-500">投稿编号（请保留在 Issue 正文，便于自动关联）</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 font-mono text-sm" value={detail.submission_id || ''} /><button className="btn-ghost text-xs" onClick={() => copySubmissionText(detail.submission_id || '', toast, '投稿编号')}>复制</button></div></div>
            <div><div className="mb-1 text-xs text-surface-500">上游 Mod 来源和依赖关系证据</div><textarea readOnly className="input-cyber min-h-36 w-full resize-y font-mono text-[11px]" value={detail.source_evidence || '此旧投稿未保存来源与依赖字段；请使用最新版本重新导出，或从 JSON 清单补充。'} /><button className="btn-ghost mt-2 text-xs" onClick={() => copySubmissionText(detail.source_evidence || '', toast, '来源与依赖说明')}>复制来源与依赖</button></div>
            <div><div className="mb-1 text-xs text-surface-500">兼容性说明、冲突和警告</div><textarea readOnly className="input-cyber min-h-24 w-full resize-y text-sm" value={detail.compatibility || detail.warning || '请补充兼容性、冲突和安装警告。'} /><button className="btn-ghost mt-2 text-xs" onClick={() => copySubmissionText(detail.compatibility || detail.warning || '', toast, '兼容性说明')}>复制兼容性说明</button></div>
          </div>
          <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-surface-600 pt-4"><button className="btn-ghost" onClick={() => openExternal(ISSUE_BASE)}><ExternalLink size={14} /> 再次打开官方投稿表单</button><button className="btn-cyber" onClick={linkIssueFromClipboard}>从剪贴板关联 Issue</button><button className="btn-ghost" onClick={() => setShowSubmissionHelper(false)}>稍后关联</button></div>
        </div>
      </div>}
    </div>
  )
}
