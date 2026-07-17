import React from 'react'
import { Zap } from 'lucide-react'

export default function PlanCard({ text }) {
  return (
    <div className="my-2 p-3 rounded-lg bg-cyber-cyan/5 border border-cyber-cyan/20 shadow-[0_0_12px_rgba(0,212,255,0.05)]">
      <div className="flex items-center gap-2 mb-2">
        <Zap size={14} className="text-cyber-cyan" />
        <span className="text-xs font-semibold text-cyber-cyan uppercase tracking-wider">执行计划</span>
      </div>
      <p className="text-xs text-surface-300 leading-relaxed">{text}</p>
    </div>
  )
}
