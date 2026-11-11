import React, { useState, useRef } from 'react'
import { AlertTriangle, Download, Hash, Link2, X } from 'lucide-react'
import { requestLocalJson, localApiFailure } from './localApi.mjs'
import { readShareResult, validateSharePreview, shareRejectionMessage, installedShareVersionLabel, shareFileStateLabel } from './shareResponse.mjs'
import { validateOfficialPreview } from './officialShareResponse.mjs'

function labelFor(item, language) {
  const en = language === 'en'
  if (item.status === 'already_installed') return `${installedShareVersionLabel(item, language)} · ${shareFileStateLabel(item, language)}`
  if (item.status === 'ready_for_source_verification') return en ? 'Source verification pending' : '待核验来源'
  if (item.status === 'needs_source_resolution') return en ? 'Source missing' : '缺少来源'
  return en ? 'Verification pending' : '待核验'
}

export default function CommunityImportDialog({ api, toast, onClose, onPlan, language = 'zh-CN' }) {
  const en = language === 'en'
  const [value, setValue] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)

  const inspect = async () => {
    if (busyRef.current) return
    const input = value.trim()
    if (!input) { toast(en ? 'Enter an ma collection code or paste a share JSON / Raw link.' : '请输入 ma 合集码，或粘贴分享 JSON / Raw 链接', 'error'); return }
    busyRef.current = true
    setBusy(true)
    setPreview(null)
    try {
      const official = /^ma-[a-z0-9][a-z0-9_-]{1,47}-\d{6}$/i.test(input)
      const officialCode = official ? input.toLowerCase() : ''
      const envelope = await requestLocalJson(`${api}/tool/${official ? 'official_share_import' : 'share_import'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(official ? { share_id: officialCode } : { share: input }),
      })
      const data = readShareResult(envelope)
      const result = official ? validateOfficialPreview(data, officialCode) : validateSharePreview(data)
      setPreview({ ...result, _verifiedInput: input, _officialCode: officialCode })
      toast(en ? `Read-only verification complete: ${result.summary?.total || 0} Mods. Nothing has been downloaded or installed.` : `已完成只读核验：${result.summary?.total || 0} 个 Mod，尚未下载或安装。`)
    } catch (error) {
      setPreview(null)
      toast('[SHARE_IMPORT_FAILED] ' + (error?.code === 'SHARE_VERIFICATION_REJECTED' ? shareRejectionMessage(language) : localApiFailure(error, language)), 'error')
    } finally {
      setBusy(false)
      busyRef.current = false
    }
  }

  const startPlan = (action = 'install_plan') => {
    if (!preview || busyRef.current || preview._verifiedInput !== value.trim() || !preview.items.length) return
    if (action === 'install_plan' && prerequisitesPending) return
    if (preview._officialCode) onPlan?.({ type: 'official', shareId: preview._officialCode, action })
    else onPlan?.({ type: 'private', share: preview._verifiedInput, action })
    onClose?.()
  }

  const title = preview?.official?.title || preview?.title || (en ? 'Shared collection preview' : '分享配置预览')
  const warning = preview?.official?.warnings?.[0] || preview?.warning || ''
  const hostRequirements = preview?.summary?.host_dependency_requirements || []
  const pendingHostRequirements = hostRequirements.filter(item => ![
    'satisfied_base_environment', 'satisfied_installed', 'included_collection',
  ].includes(item.status))
  const prerequisitesPending = pendingHostRequirements.length > 0

  const dependencyLabel = item => {
    if (item.status === 'satisfied_base_environment') return en ? 'Base environment detected' : '基础环境已检测到'
    if (item.status === 'base_environment_not_found') return en ? 'Base environment missing' : '缺少基础环境'
    if (item.status === 'needs_external_resolution') return en ? 'Prerequisite required' : '需补齐前置'
    if (item.status === 'collection_version_review') return en ? 'Version review required' : '版本需确认'
    if (item.status === 'satisfied_installed') return en ? 'Installed prerequisite detected' : '已检测到安装的前置'
    if (item.status === 'included_collection') return en ? 'Included in collection' : '已包含在合集中'
    return en ? 'Verification pending' : '待核验'
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4" onClick={() => !busy && onClose?.()}>
      <div className="flex max-h-[88vh] w-[min(94vw,640px)] flex-col rounded-xl border border-cyber-cyan/35 bg-surface-800 p-5 shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-white"><Download size={17} className="text-cyber-cyan" />{en ? 'Import a community collection' : '导入社区合集'}</h3>
            <p className="mt-1 text-xs leading-relaxed text-surface-400">{en ? 'Enter an official `ma-xxxxxx` collection code, or paste a private share JSON / GitHub Raw link. Import only previews and verifies; it never installs automatically.' : '输入官方 `ma-xxxxxx` 合集码，或粘贴私人分享 JSON / GitHub Raw 链接。导入只会预览和核验，绝不会自动安装。'}</p>
          </div>
          <button className="btn-ghost p-1.5" disabled={busy} onClick={onClose} title={en ? 'Close' : '关闭'}><X size={16} /></button>
        </div>

        <div className="flex gap-2">
          <input className="input-cyber min-w-0 flex-1" value={value} readOnly={busy} onChange={event => { setValue(event.target.value); setPreview(null) }} onKeyDown={event => { if (event.key === 'Enter') inspect() }} placeholder={en ? 'Example: ma-repo-000002, or paste a JSON / Raw link' : '例如：ma-repo-000002，或粘贴 JSON / Raw 链接'} />
          <button className="btn-cyber shrink-0" disabled={busy} onClick={inspect}>{busy ? (en ? 'Verifying…' : '核验中…') : (en ? 'Import and verify' : '导入并核验')}</button>
        </div>

        {preview && (
          <div className="mt-4 min-h-0 space-y-3 overflow-y-auto rounded-lg border border-surface-600 bg-surface-900/50 p-4 text-xs">
            <div className="flex items-start justify-between gap-3">
              <div><p className="font-medium text-white">{title}</p><p className="mt-1 text-cyber-cyan">{preview.official?.id || (en ? 'Private share' : '私人分享')} · {preview.game?.name || preview.game?.slug || (en ? 'Unknown game' : '未知游戏')}</p></div>
              <span className="rounded border border-cyber-cyan/30 px-2 py-1 text-[10px] text-cyber-cyan">{en ? 'Read-only preview' : '只读预览'}</span>
            </div>
            {preview.description && <p className="leading-relaxed text-surface-400">{preview.description}</p>}
            {warning && warning !== '暂无' && <div className="flex gap-2 rounded border border-cyber-yellow/25 bg-cyber-yellow/5 p-2 text-cyber-yellow"><AlertTriangle size={14} className="mt-0.5 shrink-0" />{warning}</div>}
            <div className="grid grid-cols-2 gap-2 text-surface-400 sm:grid-cols-4">
              <span>{en ? `Total ${preview.summary?.total || 0}` : `共 ${preview.summary?.total || 0} 项`}</span><span>{en ? `Installed ${preview.summary?.already_installed || 0}` : `已装 ${preview.summary?.already_installed || 0}`}</span><span>{en ? `To verify ${preview.summary?.needs_verification || 0}` : `待核验 ${preview.summary?.needs_verification || 0}`}</span><span>{en ? `No source ${preview.summary?.needs_source_resolution || 0}` : `缺来源 ${preview.summary?.needs_source_resolution || 0}`}</span>
            </div>
            <div className="max-h-40 space-y-1 overflow-y-auto border-t border-surface-700 pt-2">
{(preview.items || []).map((item, index) => <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3"><span className="truncate text-surface-300">{item.localized_name || item.name}</span><span className="max-w-[65%] shrink-0 break-words text-right text-[10px] text-surface-500">{labelFor(item, language)}</span></div>)}
            </div>
            {preview.items.some(item => item.status === 'already_installed') && <p className="text-cyber-yellow">{en ? 'Installed means a matching source was found in local records. Matching version text does not verify file contents, enabled state or game settings. Review differences in the plan; nothing is updated automatically.' : '已安装表示本机记录匹配到同一来源；版本文字相同不代表文件内容、启用状态或游戏配置一致。请在计划中核对差异，不会自动更新。'}</p>}
            {hostRequirements.length > 0 && <div className={`rounded border p-2.5 ${prerequisitesPending ? 'border-cyber-yellow/25 bg-cyber-yellow/5 text-cyber-yellow' : 'border-cyber-green/25 bg-cyber-green/5 text-cyber-green'}`}><p className="font-medium">{prerequisitesPending ? (en ? `${pendingHostRequirements.length} prerequisites need attention on this computer` : `本机仍需处理 ${pendingHostRequirements.length} 项前置`) : (en ? 'Listed prerequisites are satisfied or included in the collection' : '所列前置已满足或包含在合集中')}</p><p className="mt-1 text-[11px] leading-relaxed opacity-90">{en ? 'Base environment checks are separate from collection Mods. Resolve missing prerequisites and version questions before creating the main installation plan.' : '基础环境检查与合集 Mod 分开显示。缺失的前置或待确认的版本需先处理，再生成主体安装计划。'}</p><div className="mt-2 max-h-20 space-y-1 overflow-y-auto text-[11px]">{hostRequirements.map(item => <div key={item.id}>• {item.name} <span className="opacity-75">— {dependencyLabel(item)}{item.evidence?.length ? ` (${item.evidence.join(', ')})` : ''}</span></div>)}</div></div>}
            <p className="border-t border-surface-700 pt-2 leading-relaxed text-surface-500">{en ? 'This preview reads the collection and compares local records. Source availability and compatibility may still need verification in the plan. Downloads and file changes require final confirmation.' : '此预览读取合集并比对本机记录；来源可用性与兼容性仍可能需要在计划中核验。任何下载与文件修改都需要最终确认。'}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <button className="btn-cyber flex items-center justify-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-40" disabled={busy || prerequisitesPending || !preview.items.length} onClick={() => startPlan('install_plan')} title={prerequisitesPending ? (en ? 'Resolve prerequisites first' : '请先检查并补齐所列前置依赖') : (en ? 'Create a Mod installation plan' : '进入主体 Mod 安装计划')}><Hash size={14} />{en ? 'Create installation plan' : '生成安装计划'}</button>
              {prerequisitesPending ? <button disabled={busy || !preview.items.length} className="btn-ghost flex items-center justify-center gap-1.5 border-cyber-yellow/45 text-cyber-yellow hover:bg-cyber-yellow/10 disabled:opacity-40" onClick={() => startPlan('prerequisite_plan')}><AlertTriangle size={14} />{en ? `Review prerequisites (${pendingHostRequirements.length})` : `检查并补齐前置（${pendingHostRequirements.length}）`}</button> : <div className="flex items-center justify-center rounded border border-cyber-green/20 bg-cyber-green/5 px-3 text-[11px] text-cyber-green">{!preview.items.length ? (en ? 'The collection is empty; no installation plan is available.' : '合集为空，无法生成安装计划。') : (en ? 'No unresolved prerequisites reported in this preview.' : '本次预览未报告待处理的前置。')}</div>}
            </div>
          </div>
        )}
        {!preview && <p className="mt-4 flex items-center gap-1.5 text-[11px] text-surface-500"><Link2 size={12} />{en ? 'Official codes are read from the reviewed GitHub repository. Private shares are not added to official recommendations.' : '官方码从审核 GitHub 库读取；私人分享不进入官方推荐库。'}</p>}
      </div>
    </div>
  )
}
