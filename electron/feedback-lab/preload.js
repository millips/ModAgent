const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('feedbackLab', {
  listAudio: () => ipcRenderer.invoke('lab:list-audio'),
  readAudio: path => ipcRenderer.invoke('lab:read-audio', path),
  pickAudio: () => ipcRenderer.invoke('lab:pick-audio'),
  readPickedAudio: path => ipcRenderer.invoke('lab:read-picked-audio', path),
  savePreset: preset => ipcRenderer.invoke('lab:save-preset', preset),
})
