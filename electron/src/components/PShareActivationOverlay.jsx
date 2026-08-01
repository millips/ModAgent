import React from 'react'
import { ArrowRight, CheckCircle2, Sparkles } from 'lucide-react'
import { usePShareProfile } from '../pshare/pShareStore'

export default function PShareActivationOverlay({ onClose }) {
  const profile = usePShareProfile()

  return (
    <div className="p-share-activation-overlay" role="dialog" aria-modal="true" aria-label="P Share 创作者计划已开通">
      <div className="p-share-activation-panel">
        <div className="p-share-core" aria-hidden="true">
          <span className="p-share-core-ring p-share-core-ring-a" />
          <span className="p-share-core-ring p-share-core-ring-b" />
          <span className="p-share-core-star p-share-core-star-a" />
          <span className="p-share-core-star p-share-core-star-b" />
          <span className="p-share-core-nucleus"><Sparkles size={35} strokeWidth={1.6} /></span>
        </div>
        <div className="p-share-activation-copy">
          <div className="p-share-kicker">P SHARE CREATOR</div>
          <h2>分享者权限已点亮</h2>
          <p>{profile?.display_name ? `${profile.display_name}，` : ''}你现在可以将已对齐的 Mod 合集导出为待审核投稿。</p>
          <div className="p-share-activation-safe"><CheckCircle2 size={15} /> 仅保存投稿元数据；不会读取或上传你的许可证、API Key 与本机路径。</div>
        </div>
        <button type="button" className="btn-cyber p-share-enter" onClick={onClose}>
          进入分享者主页 <ArrowRight size={16} />
        </button>
      </div>
    </div>
  )
}
