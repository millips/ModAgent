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

function buildSourceEvidence(mods, language) {
  const sources = mods.map(mod => `- ${mod.name_cn || mod.name}: ${mod.sourceUrl}`).join('\n')
  const dependencies = [...new Set(mods.flatMap(mod => Array.isArray(mod.dependencies) ? mod.dependencies : []))]
  const en = language === 'en'
  return [
    en ? 'Upstream Mod sources:' : '上游 Mod 来源：',
    sources || (en ? '- None recorded' : '- 无'),
    '',
    en ? 'Dependencies:' : '依赖关系：',
    dependencies.length ? dependencies.map(item => `- ${item}`).join('\n') : (en ? '- No additional prerequisite recorded; import will verify again.' : '- 未记录额外前置；导入时仍会重新核验。'),
  ].join('\n')
}

async function copyText(text, toast, label, language) {
  try {
    await navigator.clipboard.writeText(text)
    toast(language === 'en' ? `${label} copied.` : `${label}已复制。`)
  } catch (_) {
    toast(language === 'en' ? `Could not copy ${label}; select the text manually.` : `无法复制${label}，请手动选择文本。`, 'error')
  }
}

export default function ShareExportDialog({ api, mods, toast, onClose, gameName = '', gameSlug = '', language = 'zh-CN' }) {
  const en = language === 'en'
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [warning, setWarning] = useState('')
  const [sourceEvidence, setSourceEvidence] = useState(() => buildSourceEvidence(mods, language))
  const [compatibility, setCompatibility] = useState(() => en ? `Target game: ${gameName || 'enter the game name on GitHub'}.\nThe receiving computer will check dependencies, conflicts, versions and local duplicates again before installation.` : `适用游戏：${gameName || '请填写游戏名称'}。\n安装前会在接收方电脑上重新检查依赖、冲突、版本和本机重复项。`)
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
      toast(en ? 'Enter a collection title and description.' : '请填写合集标题和简介', 'error')
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
      toast(en ? `Submission package exported: ${mods.length} Mods. Continue to the official submission page.` : `投稿包已导出：${mods.length} 个 Mod。下一步可前往官方审核投稿页。`)
    } catch (error) {
      toast(error?.message || (en ? 'Could not export the submission package.' : '导出投稿包失败'), 'error')
    } finally {
      setBusy(false)
    }
  }

  const openSubmissionPage = async () => {
    setBusy(true)
    try {
      const result = await window.modagent?.openExternal?.(OFFICIAL_SUBMISSION_URL)
      if (!result?.ok) throw new Error(result?.error || (en ? 'Could not open the submission page.' : '无法打开审核投稿页'))
      if (exported?.submissionId) updatePShareSubmission(exported.submissionId, { status: 'submission_opened' })
    } catch (error) {
      toast(error?.message || (en ? 'Could not open the submission page.' : '无法打开审核投稿页'), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4">
      <div className="flex max-h-[88vh] w-[min(94vw,680px)] flex-col rounded-xl border border-cyber-cyan/35 bg-surface-800 p-5 shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-white"><FileText size={17} className="text-cyber-cyan" />{en ? 'Create a shared collection' : '创建分享合集'}</h3>
            <p className="mt-1 text-xs leading-relaxed text-surface-400">{en ? `Exports the title, sources, dependencies, enable state and ordering for ${mods.length} selected Mods. It never includes Mod files, API keys, game paths or local file paths.` : `将导出 ${mods.length} 个已选 Mod 的标题、来源、依赖、启用状态和排序；不会包含 Mod 文件、API Key、游戏路径或本机文件路径。`}</p>
          </div>
          <button className="btn-ghost p-1.5" disabled={busy} onClick={onClose} title={en ? 'Close' : '关闭'}><X size={16} /></button>
        </div>

        {exported ? (
          <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
            <div className="rounded-lg border border-cyber-green/35 bg-cyber-green/5 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-cyber-green"><CheckCircle2 size={17} />{en ? 'Submission package exported' : '投稿包已导出'}</div>
              <p className="mt-2 text-xs leading-relaxed text-surface-300">
                {en ? <>Created <span className="font-mono text-cyber-cyan">{exported.filename}</span>. This local file is not public and has not received an official collection code.</> : <>已生成 <span className="font-mono text-cyber-cyan">{exported.filename}</span>。该文件目前仅在本机，尚未公开，也没有获得官方合集码。</>}
              </p>
              {exported.submissionId && <p className="mt-2 text-xs text-surface-500">{en ? 'Draft submission ID: ' : '投稿草稿编号：'}{exported.submissionId}</p>}
            </div>
            <div className="rounded-lg border border-cyber-cyan/25 bg-surface-900/70 p-4 text-xs space-y-3">
              <div className="flex items-center justify-between gap-3"><span className="font-medium text-white">{en ? 'GitHub submission fields' : 'GitHub 投稿字段（已按官方表单生成）'}</span><span className="text-cyber-cyan">{en ? 'Copy and paste' : '复制后粘贴即可'}</span></div>
              <div><div className="mb-1 text-surface-500">{en ? 'Title' : '标题'}</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-xs" value={`[Collection]: ${title.trim()}`} /><button type="button" className="btn-ghost text-[11px]" onClick={() => copyText(`[Collection]: ${title.trim()}`, toast, en ? 'Title' : '标题', language)}>{en ? 'Copy' : '复制'}</button></div></div>
              <div><div className="mb-1 text-surface-500">{en ? 'Game and game slug' : '游戏和游戏启动器'}</div><div className="flex gap-2"><input readOnly className="input-cyber flex-1 text-xs" value={gameName || gameSlug || (en ? 'Enter the game name in GitHub' : '请在 GitHub 表单填写游戏名称')} /><button type="button" className="btn-ghost text-[11px]" onClick={() => copyText(gameName || gameSlug || '', toast, en ? 'Game information' : '游戏信息', language)}>{en ? 'Copy' : '复制'}</button></div></div>
              <div><div className="mb-1 text-surface-500">{en ? 'Upstream sources and dependency evidence' : '上游 Mod 来源和依赖关系证据'}</div><textarea readOnly className="input-cyber min-h-28 w-full resize-y font-mono text-[11px]" value={sourceEvidence} /><button type="button" className="btn-ghost mt-2 text-[11px]" onClick={() => copyText(sourceEvidence, toast, en ? 'Source and dependency notes' : '来源与依赖说明', language)}>{en ? 'Copy source and dependency notes' : '复制来源与依赖说明'}</button></div>
              <div><div className="mb-1 text-surface-500">{en ? 'Compatibility, conflicts and warnings' : '兼容性说明、冲突和警告'}</div><textarea readOnly className="input-cyber min-h-20 w-full resize-y text-xs" value={compatibility} /><button type="button" className="btn-ghost mt-2 text-[11px]" onClick={() => copyText(compatibility, toast, en ? 'Compatibility notes' : '兼容性说明', language)}>{en ? 'Copy compatibility notes' : '复制兼容性说明'}</button></div>
              <p className="text-surface-500">{en ? <>On GitHub, drag <span className="font-mono text-cyber-cyan">{exported.filename}</span> to the attachment area below “JSON manifest or pull request URL”; GitHub will create a direct link.</> : <>打开 GitHub 后：把 <span className="font-mono text-cyber-cyan">{exported.filename}</span> 拖到「JSON 清单或拉取请求 URL」字段下方的附件区；GitHub 上传后会生成可粘贴的直接链接。</>}</p>
            </div>
            <div className="rounded-lg border border-surface-600 bg-surface-900/50 p-3 text-xs leading-relaxed text-surface-400">
              {en ? <>Next: open the official GitHub submission page, attach the exported JSON and submit it. After review, the official repository assigns a unique <span className="font-mono text-cyber-cyan">ma-xxxxxx</span> collection code.</> : <>下一步：打开官方 GitHub 投稿页，按表单要求附上刚导出的 JSON 文件并提交。审核通过后，由官方仓库分配唯一的 <span className="font-mono text-cyber-cyan">ma-xxxxxx</span> 合集码。</>}
            </div>
          </div>
        ) : (
        <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
          <label className="block text-xs text-surface-300">{en ? 'Collection title' : '合集标题'} <span className="text-cyber-red">*</span>
            <input className="input-cyber mt-1 w-full" maxLength={100} value={title} onChange={event => setTitle(event.target.value)} placeholder={en ? 'Example: a lightweight co-op collection for beginners' : '例如：REPO 新手联机轻量合集'} />
          </label>
          <label className="block text-xs text-surface-300">{en ? 'Description' : '简介'} <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-24 w-full resize-y" maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} placeholder={en ? 'Who this is for, what it solves and how to play it.' : '适合什么玩家、解决什么需求、推荐的游玩方式。'} />
          </label>
          <label className="block text-xs text-surface-300">{en ? 'Warnings and installation notes' : '警告与安装注意事项'}
            <textarea className="input-cyber mt-1 min-h-20 w-full resize-y" maxLength={2000} value={warning} onChange={event => setWarning(event.target.value)} placeholder={en ? 'Optional: back up saves, all co-op players install it, incompatible with a named Mod.' : '可选：例如建议备份存档、联机房主与成员都需安装、不可与某 Mod 共用。'} />
          </label>
          <label className="block text-xs text-surface-300">{en ? 'Creator display name' : '作者昵称'}
            <input className="input-cyber mt-1 w-full" maxLength={80} value={authorName} onChange={event => setAuthorName(event.target.value)} placeholder={en ? 'Optional; this does not use or upload your license information.' : '可选；不使用 License ID，也不会上传你的授权信息。'} />
          </label>

          <label className="block text-xs text-surface-300">{en ? 'Upstream sources and dependency evidence' : '上游 Mod 来源和依赖关系证据'} <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-32 w-full resize-y font-mono text-[11px]" maxLength={5000} value={sourceEvidence} onChange={event => setSourceEvidence(event.target.value)} />
            <span className="mt-1 block text-[10px] text-surface-500">{en ? 'Generated from aligned source pages and recorded dependencies. Add any real prerequisite that is not listed.' : '已根据对齐后的原始发布页和本机已记录依赖自动生成；请补充未记录但确实需要的前置。'}</span>
          </label>
          <label className="block text-xs text-surface-300">{en ? 'Compatibility, conflicts and warnings' : '兼容性说明、冲突和警告'} <span className="text-cyber-red">*</span>
            <textarea className="input-cyber mt-1 min-h-24 w-full resize-y" maxLength={3000} value={compatibility} onChange={event => setCompatibility(event.target.value)} />
          </label>

          <div className="rounded-lg border border-surface-600 bg-surface-900/50 p-3 text-xs">
            <div className="mb-2 flex items-center gap-1.5 text-surface-200"><Link2 size={13} className="text-cyber-cyan" />{en ? `Verified sources ${mods.length - unaligned.length}/${mods.length}` : `已核验来源 ${mods.length - unaligned.length}/${mods.length}`}</div>
            {unaligned.length ? (
              <div className="flex gap-2 text-cyber-yellow"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><p>{en ? `These Mods have not been source-aligned, so they cannot be exported: ${unaligned.map(mod => mod.name_cn || mod.name).join(', ')}. Align them in Mod Manager first.` : `以下 Mod 尚未完成来源对齐，不能作为投稿包导出：${unaligned.map(mod => mod.name_cn || mod.name).join('、')}。请先在管理页完成“对齐”。`}</p></div>
            ) : (
              <p className="text-surface-500">{en ? 'Every selected item has an aligned original source page. The receiving computer will still verify dependencies, versions, conflicts and local installation state on import.' : '所有已选项都有已对齐的原始发布页；接收者仍会在导入时重新核验依赖、版本、冲突与本机已安装状态。'}</p>
            )}
          </div>
        </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-surface-600 pt-4">
          {exported ? <>
            <button className="btn-ghost" disabled={busy} onClick={onClose}>{en ? 'Submit later' : '稍后投稿'}</button>
            <button className="btn-cyber flex items-center gap-1.5" disabled={busy} onClick={openSubmissionPage}>
              <Github size={14} /> {en ? 'Open official submission page' : '前往官方审核投稿页'}
            </button>
          </> : <>
            <button className="btn-ghost" disabled={busy} onClick={onClose}>{en ? 'Cancel' : '取消'}</button>
            <button className="btn-cyber flex items-center gap-1.5 disabled:opacity-40" disabled={!ready || busy} onClick={exportSubmission} title={ready ? (en ? 'Export JSON for official review' : '导出待审核投稿 JSON') : (en ? 'Align the source for every selected Mod first' : '请先完成所有已选 Mod 的来源对齐')}>
              <Download size={14} />{busy ? (en ? 'Exporting…' : '正在导出…') : (en ? 'Export submission JSON' : '导出投稿包 JSON')}
            </button>
          </>}
        </div>
      </div>
    </div>
  )
}
