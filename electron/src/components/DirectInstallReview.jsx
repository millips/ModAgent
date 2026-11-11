import React from 'react'

export default function DirectInstallReview({review, language}) {
  const en=language==='en'
  const report=review.report || {}
  const files=review.fileReport || report
  const paths=Array.isArray(files.planned_files)?files.planned_files:[]
  const conflicts=Array.isArray(files.conflicts)?files.conflicts:[]
  return <section className="mb-4 text-xs space-y-3" aria-label={en?'Installation review':'安装核验'}>
    <p className="font-medium text-white">{review.name || (en?'Downloaded package':'已下载的安装包')}</p>
    <p>{en?'File preview only: dependency and compatibility checks may still block installation. In-game behavior has not been verified.':'此处为文件预览；依赖和兼容性检查仍可能阻止安装，游戏内效果尚未验证。'}</p>
    <div className="flex gap-4"><span>{en?'Planned files: ':'计划写入文件：'}{Number.isInteger(files.incoming_files_count)?files.incoming_files_count:(en?'Unknown':'未知')}</span><span>{en?'File conflicts: ':'文件冲突：'}{conflicts.length}</span></div>
    {!!paths.length && <details open><summary>{en?'Target files':'目标文件'}</summary><ul className="max-h-28 overflow-auto break-all p-2">{paths.map((file,index)=><li key={index}>{typeof file==='string'?file:JSON.stringify(file)}</li>)}</ul></details>}
    {!!conflicts.length && <p className="text-cyber-yellow">{en?'Conflicting files must be resolved before automatic installation.':'存在文件冲突，解决后才能自动安装。'}</p>}
    {review.compatibilityRisk && <div className="rounded border border-cyber-yellow/40 p-2 text-cyber-yellow"><p>{en?'Compatibility risk: this package is not confirmed for the current game build. Continuing may cause loading failures or crashes. Confirm again only if you accept this risk.':'兼容性风险：未确认该包适配当前游戏版本。继续可能导致加载失败或崩溃，请阅读报告，接受风险后再确认。'}</p></div>}
    {!review.ready && <p className="text-cyber-yellow">{en?'Installation is blocked or not confirmed complete. Review the report and download cache. Use Chat for missing prerequisites or a custom installation plan.':'安装被阻止或未确认完整完成，请核对报告与下载缓存；缺少前置或需要自定义方案时可到对话页继续处理。'}</p>}
    {typeof report.message==='string' && <p className="whitespace-pre-wrap">{report.message}</p>}
    <details><summary>{en?'Full diagnostic report':'完整诊断报告'}</summary><pre className="max-h-52 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-900 p-2">{JSON.stringify(report,null,2)}</pre></details>
  </section>
}
