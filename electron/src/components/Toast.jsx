import React from 'react'
import { CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react'

const ICONS = { success: CheckCircle, error: XCircle, warn: AlertTriangle, info: Info }
const COLORS = { success: 'border-cyber-green/50 bg-cyber-green/5', error: 'border-cyber-red/50 bg-cyber-red/5', warn: 'border-cyber-yellow/50 bg-cyber-yellow/5', info: 'border-cyber-cyan/50 bg-cyber-cyan/5' }

export default function Toast({ msg, type = 'info' }) {
  const Icon = ICONS[type] || Info
  return (
    <div className={`animate-slide-up flex items-center gap-2 px-4 py-2.5 rounded-lg border ${COLORS[type]} text-sm text-white shadow-lg min-w-[200px]`}>
      <Icon size={14} className="shrink-0" />
      <span className="text-xs">{msg}</span>
    </div>
  )
}
