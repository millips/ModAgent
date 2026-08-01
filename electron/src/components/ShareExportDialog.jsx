import React, { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, FileText, Github, Link2, X } from 'lucide-react'
import { updatePShareSubmission, upsertPShareSubmission } from '../pshare/pShareStore'

const OFFICIAL_SUBMISSION_URL = 'https://github.com/millips/ModAgent-Share/issues/new?template=collection-submission.yml'

function downloadJson(text, filename) {
  const blob = new Blob([text], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function buildSourceEvidence(mods) {
  const sources = mods.map(mod => `- ${mod.name_cn || mod.name}: ${mod.sourceUrl}`).join('\n')
  const dependencies = [...new Set(mods.flatMap(mod => Array.isArray(mod.dependencies) ? mod.dependencies : []))]
  return [
    '上游 Mod 来源：',
    sources || '- 无',
    '',
    '依赖关系：',
    dependencies.length ? dependencies.map(item => `- ${item}`).join('\n') : '- 未记录额外前置；导入时仍会重新核验。',
  ].join('\n')
}

async function copyText(text, toast, label) {
  try {
    await navigator.clipboard.writeText(text)
    toast(`${label}已复制。`)
  } catch (_) {
    toast(`无法复制${label}，请手动选择文本。`, 'error')
  }
}

export default function ShareExportDialog({ api, mods, toast, onClose, gameName = '', gameSlug = '' }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [warning, setWarning] = useState('')
  const [sourceEvidence, setSourceEvidence] = useState(() => buildSourceEvidence(mods))
  const [compatibility, setCompatibility] = useState(() => `适用游戏：${gameName || '请填写游戏名称'}。\n安装前会在接收方电脑上重新检查依赖、冲突、版本和本机重复项。`)
  const [authorName, setAuthorName] = useState('')
  const [busy, setBusy] = useState(false)
  const [exported, setExported] = useState(null)

  const unaligned = useMemo(
    () => mods.filter(mod => !(mod.sourceKey && mod.sourceUrl)),
    [mods],
  )
  const ready = unaligned.length === 0 && mods.length > 0

  const exportSubmission = async () => {
    if (!title.trim() || !description.trim() || !sourceEvidence.trim() || !compatibility.trim()) {
      toast('请填写合集标题和简介', 'error')
      return
    }
    if (!ready || busy) return
    setBusy(true)
    try {
      const response = await fetch(`${api}/tool/share_export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selected_mod_ids: mods.map(mod => String(mod.id)),
          title: title.trim(),
          description: description.trim(),
          warning: warning.trim(),
          author_note: `${sourceEvidence.trim()}\n\n兼容性、冲突和警告：\n${compatibility.trim()}`.slice(0, 2000),
          author_name: authorName.trim(),
          source_evidence: sourceEvidence.trim(),
          compatibility: compatibility.trim(),
          require_verified_sources: true,
        }),
      })
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error) throw new Error(result.error)
      const safeTitle = title.trim().replace(/[\\/:*?"<>|]+/g, '-').slice(0, 48) || 'collection'
      const submissionId = result.manifest?.submission?.id || ''
      const filename = `modagent-submission-${submissionId || Date.now()}-${safeTitle}.json`
      downloadJson(result.share_json, filename)
      upsertPShareSubmission({
        submission_id: submissionId,
        title: title.trim(),
        description: description.trim(),
        warning: warning.trim(),
        source_evidence: sourceEvidence.trim(),
        compatibility: compatibility.trim(),
        author_name: authorName.trim(),
        game_name: gameName,
        game_slug: gameSlug,
        mod_count: mods.length,
        filename,
      })
      setExported({
        submissionId,
        filename,
      })
      toast(`投稿包已导出：${mods.length} 个 Mod。下一步可前往官方审核投稿页。`)
    } catch (error) {
      toast(error?.message || '导出投稿包失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const openSubmissionPage = async () => {
    setBusy(true)
    try {
      const result = await window.modagent?.openExternal?.(OFFICIAL_SUBMISSION_URL)
      if (!result?.ok) throw new Error(result?.error || '无法打开审核投稿页')
      if (exported?.submissionId) updatePShareSubmission(exported.submissionId, { status: 'submission_opened' })
    } catch (error) {
      toast(error?.message || '无法打开审核投稿页', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4">
      <div className="flex max-h-[88vh] w-[min(94vw,680px)] flex-col rounded-xl border border-cyber-cyan/35 bg-surface-800 p-5 shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-white"><FileText size={17} className="text-cyber-cyan" />创建分享合集</h3>
            <p className="mt-1 text-xs leading-relaxed text-surface-400">将导出 {mods.length} 个已选 Mod 的标题、来源、依赖、启用状态和排序；不会包含 Mod 文件、API Key、游戏路径或本机文件路径。</p>
          </div>
          <button className="btn-ghost p-1.5" disabled={busy} onClick={onClose} title="关闭"><X size={16} /></button>
        </div>

        {exported ? (
          <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
            <div className="rounded-lg border border-cyber-green/35 bg-cyber-green/5 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-cyber-green"><CheckCircle2 size={17} />投稿包已导出</div>
              <p className="mt-2 text-xs leading-relaxed text-surface-300">
                已生成 <span className="font-mono text-cyber-cyan">{exported.filename}</span>。该文件目前仅在本机，尚未公开，也没有获得官方合集码。
              </p>
              {exported.submissionId && <p className="mt-2 text-xs text-surface-500">投稿草稿编号：{exported.submissionId}</p>}
            </div>
            <div className="rounded-lg border border-cyber-cyan/25 bg-surface-900/70 p-4 text-xs space-y-3">
              <div className="flex items-center justify-between gap-3"><span className="font-medium text-white">GitHub 投稿字段（已按官方表单生成）</span><span className="text-cyber-cyan">复制后粘贴即可</span></div>
              <div><div className="mb-1 text-surface-500">标题</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-xs" value={`[Collection]: ${title.trim()}`} /><button type="button" className="btn-ghost text-[11px]" onClick={() => copyText(`[Collection]: ${title.trim()}`, toast, '标题')}>复制</button></div></div>
              <div><div className="mb-1 text-surface-500">游戏和游戏启动器</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-xs" value={gameName || gameSlug || '请在 GitHub 表单填写游戏名称'} /><button type="button" className="btn-ghost text-[11px]" onClick={() => copyText(gameName || gameSlug || '', toast, '游戏信息')}>复制</button></div></div>
              <div><div className="mb-1 text-surface-500">上游 Mod 来源和依赖关系证据</div><textarea readOnly className="input-cyber min-h-28 w-full resize-y font-mono text-[11px]" value={sourceEvidence} /><button type="button" className="btn-ghost mt-2 text-[11px]" onClick={() => copyText(sourceEvidence, toast, '来源与依赖说明')}>复制来源与依赖说明</button></div>
              <div><div className="mb-1 text-surface-500">兼容性说明、冲突和警告</div><textarea readOnly className="input-cyber min-h-20 w-full resize-y text-xs" value={compatibility} /><button type="button" className="btn-ghost mt-2 text-[11px]" onClick={() => copyText(compatibility, toast, '兼容性说明')}>复制兼容性说明</button></div>
              <p className="text-surface-500">打开 GitHub 后：把 <span className="font-mono text-cyber-cyan">{exported.filename}</span> 拖到「JSON 清单或拉取请求 URL」字段下方的附件区；GitHub 上传后会生成可粘贴的直接链接。</p>
            </div>
            <div className="rounded-lg border border-surface-600 bg-surface-900/50 p-3 text-xs leading-relaxed text-surface-400">
              下一步：打开官方 GitHub 投稿页，按表单要求附上刚导出的 JSON 文件并提交。审核通过后，由官方仓库分配唯一的 <span className="font-mono text-cyber-cyan">ma-xxxxxx</span> 合集码。
            </div>
          </div>
        ) : (
        <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
          <label className="block text-xs text-surface-300">合集标题 <span className="text-cyber-red">*</span>
            <input className="input-cyber mt-1 w-full" maxLength={100} value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：REPO 新手联机轻量合集" />
          </label>
          <label className="block text-xs text-surface-300">简介 <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-24 w-full resize-y" maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} placeholder="适合什么玩家、解决什么需求、推荐的游玩方式。" />
          </label>
          <label className="block text-xs text-surface-300">警告与安装注意事项
            <textarea className="input-cyber mt-1 min-h-20 w-full resize-y" maxLength={2000} value={warning} onChange={event => setWarning(event.target.value)} placeholder="可选：例如建议备份存档、联机房主与成员都需安装、不可与某 Mod 共用。" />
          </label>
          <label className="block text-xs text-surface-300">作者昵称
            <input className="input-cyber mt-1 w-full" maxLength={80} value={authorName} onChange={event => setAuthorName(event.target.value)} placeholder="可选；不使用 License ID，也不会上传你的授权信息。" />
          </label>

          <label className="block text-xs text-surface-300">上游 Mod 来源和依赖关系证据 <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-32 w-full resize-y font-mono text-[11px]" maxLength={5000} value={sourceEvidence} onChange={event => setSourceEvidence(event.target.value)} />
            <span className="mt-1 block text-[10px] text-surface-500">已根据对齐后的原始发布页和本机已记录依赖自动生成；请补充未记录但确实需要的前置。</span>
          </label>
          <label className="block text-xs text-surface-300">兼容性说明、冲突和警告 <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-24 w-full resize-y" maxLength={3000} value={compatibility} onChange={event => setCompatibility(event.target.value)} />
          </label>

          <div className="rounded-lg border border-surface-600 bg-surface-900/50 p-3 text-xs">
            <div className="mb-2 flex items-center gap-1.5 text-surface-200"><Link2 size={13} className="text-cyber-cyan" />已核验来源 {mods.length - unaligned.length}/{mods.length}</div>
            {unaligned.length ? (
              <div className="flex gap-2 text-cyber-yellow"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><p>以下 Mod 尚未完成来源对齐，不能作为投稿包导出：{unaligned.map(mod => mod.name_cn || mod.name).join('、')}。请先在管理页完成“对齐”。</p></div>
            ) : (
              <p className="text-surface-500">所有已选项都有已对齐的原始发布页；接收者仍会在导入时重新核验依赖、版本、冲突与本机已安装状态。</p>
            )}
          </div>
        </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-surface-600 pt-4">
          {exported ? <>
            <button className="btn-ghost" disabled={busy} onClick={onClose}>稍后投稿</button>
            <button className="btn-cyber flex items-center gap-1.5" disabled={busy} onClick={openSubmissionPage}>
              <Github size={14} /> 前往官方审核投稿页
            </button>
          </> : <>
            <button className="btn-ghost" disabled={busy} onClick={onClose}>取消</button>
            <button className="btn-cyber flex items-center gap-1.5 disabled:opacity-40" disabled={!ready || busy} onClick={exportSubmission} title={ready ? '导出待审核投稿 JSON' : '请先完成所有已选 Mod 的来源对齐'}>
              <Download size={14} />{busy ? '正在导出…' : '导出投稿包 JSON'}
            </button>
          </>}
        </div>
      </div>
    </div>
  )
}
