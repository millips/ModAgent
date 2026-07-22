import React from 'react'
import defaultWallpaper from '../assets/default-wallpaper.png'

export function bootstrapEdition() {}

export function SidebarEditionAddon() {
  return null
}

export function SettingsEditionPanel() {
  return null
}

export function ChatEditionMessage() {
  return null
}

export function applyEditionDefaultBackground() {
  document.body.classList.add('has-bg', 'default-bg')
  document.body.style.backgroundImage = `url("${defaultWallpaper}")`
}
