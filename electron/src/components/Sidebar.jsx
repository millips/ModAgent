import React from 'react'
import { MessageSquare, Package, Camera, Settings, Wifi, WifiOff, RefreshCw } from 'lucide-react'
import { SidebarEditionAddon } from '@edition'
import kawaiiChatIcon from '../assets/themes/kawaii/icons/nav-chat.png'
import kawaiiModsIcon from '../assets/themes/kawaii/icons/nav-mods.png'
import kawaiiSnapsIcon from '../assets/themes/kawaii/icons/nav-snaps.png'
import kawaiiSettingsIcon from '../assets/themes/kawaii/icons/nav-settings.png'

const NAV = [
  { id: 'chat', label: '对话', icon: MessageSquare, kawaiiIcon: kawaiiChatIcon },
  { id: 'mods', label: 'Mod 管理', icon: Package, kawaiiIcon: kawaiiModsIcon },
  { id: 'snaps', label: '快照', icon: Camera, kawaiiIcon: kawaiiSnapsIcon },
  { id: 'settings', label: '设置', icon: Settings, kawaiiIcon: kawaiiSettingsIcon },
]

export default function Sidebar({ page, onNav, status }) {
  const connecting = !status.online && status.mods == null && status.snaps == null
  return (
    <aside className="w-52 min-w-[208px] bg-surface-800 border-r border-surface-600 flex flex-col">
      <div className="p-4 border-b border-surface-600">
        <h1 className="text-lg font-bold text-cyber-cyan tracking-wide flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-cyber-cyan shadow-[0_0_8px_#00d4ff]"></span>
          ModAgent
        </h1>
        <p className="text-[11px] text-surface-500 mt-1">AI Mod Manager v1.0</p>
      </div>

      <nav className="flex-1 p-2 flex flex-col gap-0.5">
        {NAV.map(n => (
          <button
            key={n.id}
            onClick={() => onNav(n.id)}
            className={`nav-item flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all duration-150
              ${page === n.id
                ? 'nav-item-active bg-cyber-blue/15 text-cyber-cyan border border-cyber-cyan/20'
                : 'text-surface-500 hover:bg-surface-700 hover:text-white'}`}
          >
            <span className="nav-energy-scan" aria-hidden="true" />
            <n.icon size={16} className="nav-default-icon" />
            <img src={n.kawaiiIcon} className="nav-kawaii-icon" alt="" draggable="false" />
            <span className="nav-item-label">{n.label}</span>
          </button>
        ))}
      </nav>

      <SidebarEditionAddon page={page} />

      <div className="p-3 border-t border-surface-600 flex items-center gap-2 text-xs text-surface-500">
        {status.online
          ? <Wifi size={12} className="text-cyber-green" />
          : <WifiOff size={12} className="text-cyber-red" />}
        <span>{status.online ? '已连接' : connecting ? '正在启动…' : '连接中断'}</span>
        <button onClick={() => window.location.reload()} className="ml-auto p-1 rounded hover:bg-surface-700" title="刷新界面">
          <RefreshCw size={12} />
        </button>
      </div>
    </aside>
  )
}
