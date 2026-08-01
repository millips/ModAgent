import React, { useState } from 'react'
import { AlertTriangle, Download, Hash, Link2, X } from 'lucide-react'

function labelFor(item) {
  if (item.status === 'already_installed') return '已安装'
  if (item.status === 'ready_for_source_verification') return '待核验来源'
  if (item.status === 'needs_source_resolution') return '缺少来源'
  return item.status || '待核验'
}

export default function CommunityImportDialog({ api, toast, onClose, onPlan }) {
  const [value, setValue] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)

  const inspect = async () => {
    const input = value.trim()
    if (!input) { toast('请输入 ma 合集码，或粘贴分享 JSON / Raw 链接', 'error'); return }
    setBusy(true)
    try {
      const official = /^ma-[a-z0-9][a-z0-9_-]{1,47}-\d{6}$/i.test(input)
      const response = await fetch(`${api}/tool/${official ? 'official_share_import' : 'share_import'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(official ? { share_id: input } : { share: input }),
      })
      const envelope = await response.json()
      const result = JSON.parse(envelope.result || '{}')
      if (result.error) throw new Error(result.error)
      setPreview({ ...result, _officialCode: official ? input.toLowerCase() : '' })
      toast(`已完成只读核验：${result.summary?.total || 0} 个 Mod，尚未下载或安装。`)
    } catch (error) {
      setPreview(null)
      toast(error?.message || '导入核验失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const startPlan = (action = 'install_plan') => {
    if (!preview) return
    if (preview._officialCode) onPlan?.({ type: 'official', shareId: preview._officialCode, action })
    else onPlan?.({ type: 'private', share: value.trim(), action })
    onClose?.()
  }

  const title = preview?.official?.title || preview?.title || '分享配置预览'
  const warning = preview?.official?.warnings?.[0] || preview?.warning || ''
  const hostRequirements = preview?.summary?.host_dependency_requirements || []
  const pendingHostRequirements = hostRequirements.filter(item => ![
    'satisfied_base_environment', 'satisfied_installed', 'included_collection',
  ].includes(item.status))
  const prerequisitesPending = pendingHostRequirements.length > 0

  const dependencyLabel = item => {
    if (item.status === 'satisfied_base_environment') return '基础环境已检测到'
    if (item.status === 'base_environment_not_found') return '缺少基础环境'
    if (item.status === 'needs_external_resolution') return '需补齐前置'
    if (item.status === 'collection_version_review') return '版本需确认'
    return item.status || '待核验'
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4" onClick={() => !busy && onClose?.()}>
      <div className="flex max-h-[88vh] w-[min(94vw,640px)] flex-col rounded-xl border border-cyber-cyan/35 bg-surface-800 p-5 shadow-2xl animate-slide-up" onClick={event => event.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-white"><Download size={17} className="text-cyber-cyan" />导入社区合集</h3>
            <p className="mt-1 text-xs leading-relaxed text-surface-400">输入官方 `ma-xxxxxx` 合集码，或粘贴私人分享 JSON / GitHub Raw 链接。导入只会预览和核验，绝不会自动安装。</p>
          </div>
          <button className="btn-ghost p-1.5" disabled={busy} onClick={onClose} title="关闭"><X size={16} /></button>
        </div>

        <div className="flex gap-2">
          <input className="input-cyber min-w-0 flex-1" value={value} onChange={event => setValue(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') inspect() }} placeholder="例如：ma-000001，或粘贴 JSON / Raw 链接" />
          <button className="btn-cyber shrink-0" disabled={busy} onClick={inspect}>{busy ? '核验中…' : '导入并核验'}</button>
        </div>

        {preview && (
          <div className="mt-4 min-h-0 space-y-3 overflow-y-auto rounded-lg border border-surface-600 bg-surface-900/50 p-4 text-xs">
            <div className="flex items-start justify-between gap-3">
              <div><p className="font-medium text-white">{title}</p><p className="mt-1 text-cyber-cyan">{preview.official?.id || '私人分享'} · {preview.game?.name || preview.game?.slug || '未知游戏'}</p></div>
              <span className="rounded border border-cyber-cyan/30 px-2 py-1 text-[10px] text-cyber-cyan">只读预览</span>
            </div>
            {preview.description && <p className="leading-relaxed text-surface-400">{preview.description}</p>}
            {warning && warning !== '暂无' && <div className="flex gap-2 rounded border border-cyber-yellow/25 bg-cyber-yellow/5 p-2 text-cyber-yellow"><AlertTriangle size={14} className="mt-0.5 shrink-0" />{warning}</div>}
            <div className="grid grid-cols-2 gap-2 text-surface-400 sm:grid-cols-4">
              <span>共 {preview.summary?.total || 0} 项</span><span>已装 {preview.summary?.already_installed || 0}</span><span>待核验 {preview.summary?.needs_verification || 0}</span><span>缺来源 {preview.summary?.needs_source_resolution || 0}</span>
            </div>
            <div className="max-h-40 space-y-1 overflow-y-auto border-t border-surface-700 pt-2">
              {(preview.items || []).map((item, index) => <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3"><span className="truncate text-surface-300">{item.localized_name || item.name}</span><span className="shrink-0 text-[10px] text-surface-500">{labelFor(item)}</span></div>)}
            </div>
            {hostRequirements.length > 0 && <div className={`rounded border p-2.5 ${prerequisitesPending ? 'border-cyber-yellow/25 bg-cyber-yellow/5 text-cyber-yellow' : 'border-cyber-green/25 bg-cyber-green/5 text-cyber-green'}`}><p className="font-medium">{prerequisitesPending ? `导入者主机仍需处理 ${pendingHostRequirements.length} 项前置` : '基础环境已在本机检测通过'}</p><p className="mt-1 text-[11px] leading-relaxed opacity-90">基础环境不会伪装成合集 Mod。这里直接检查游戏目录；只有实际缺失或版本需确认的项才会阻止生成主体安装计划。</p><div className="mt-2 max-h-20 space-y-1 overflow-y-auto text-[11px]">{hostRequirements.map(item => <div key={item.id}>• {item.name} <span className="opacity-75">— {dependencyLabel(item)}{item.evidence?.length ? ` (${item.evidence.join(', ')})` : ''}</span></div>)}</div></div>}
            <p className="border-t border-surface-700 pt-2 leading-relaxed text-surface-500">主体 Mod、来源和本机重复项已完成预检。只有全部前置通过，才可生成主体安装计划；任何下载与写入仍会经过最终确认。</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <button className="btn-cyber flex items-center justify-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-40" disabled={prerequisitesPending} onClick={() => startPlan('install_plan')} title={prerequisitesPending ? '请先检查并补齐所列前置依赖' : '直接进入主体 Mod 安装计划'}><Hash size={14} />生成安装计划</button>
              {prerequisitesPending ? <button className="btn-ghost flex items-center justify-center gap-1.5 border-cyber-yellow/45 text-cyber-yellow hover:bg-cyber-yellow/10" onClick={() => startPlan('prerequisite_plan')}><AlertTriangle size={14} />检查并补齐前置（{pendingHostRequirements.length}）</button> : <div className="flex items-center justify-center rounded border border-cyber-green/20 bg-cyber-green/5 px-3 text-[11px] text-cyber-green">✓ 前置已满足，可生成计划</div>}
            </div>
          </div>
        )}
        {!preview && <p className="mt-4 flex items-center gap-1.5 text-[11px] text-surface-500"><Link2 size={12} />官方码从审核 GitHub 库读取；私人分享不进入官方推荐库。</p>}
      </div>
    </div>
  )
}
