const { app, BrowserWindow, ipcMain, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const os = require('os')

const DEFAULT_AUDIO_DIR = path.join(os.homedir(), 'Desktop', '音频素材')
const AUDIO_EXTS = new Set(['.mp3', '.wav', '.ogg', '.m4a', '.flac'])

function audioFiles(dir) {
  if (!dir || !fs.existsSync(dir)) return []
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const entryPath = path.join(dir, entry.name)
    if (entry.isDirectory()) return audioFiles(entryPath)
    if (!entry.isFile() || !AUDIO_EXTS.has(path.extname(entry.name).toLowerCase())) return []
    return [{ name: entry.name, path: entryPath, size: fs.statSync(entryPath).size }]
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1100, minHeight: 720,
    title: 'ModAgent · Feedback Lab', backgroundColor: '#050609',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  })
  win.loadFile(path.join(__dirname, 'index.html'))
}

ipcMain.handle('lab:list-audio', (_, dir = DEFAULT_AUDIO_DIR) => audioFiles(dir))
ipcMain.handle('lab:read-audio', (_, filePath) => {
  const resolved = path.resolve(String(filePath || ''))
  const allowedRoot = path.resolve(DEFAULT_AUDIO_DIR)
  if (!resolved.startsWith(allowedRoot + path.sep) || !fs.existsSync(resolved)) return null
  return fs.readFileSync(resolved).toString('base64')
})
ipcMain.handle('lab:pick-audio', async () => {
  const result = await dialog.showOpenDialog({
    title: '添加音频素材', properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Audio', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac'] }],
  })
  if (result.canceled) return []
  return result.filePaths.map(filePath => ({ name: path.basename(filePath), path: filePath, size: fs.statSync(filePath).size }))
})
ipcMain.handle('lab:read-picked-audio', (_, filePath) => {
  if (!filePath || !fs.existsSync(filePath) || !AUDIO_EXTS.has(path.extname(filePath).toLowerCase())) return null
  return fs.readFileSync(filePath).toString('base64')
})
ipcMain.handle('lab:save-preset', (_, preset) => {
  const dir = path.join(app.getPath('userData'), 'feedback-lab-presets')
  fs.mkdirSync(dir, { recursive: true })
  const output = path.join(dir, 'current.json')
  fs.writeFileSync(output, JSON.stringify(preset, null, 2), 'utf8')
  return output
})

app.whenReady().then(createWindow)
app.on('window-all-closed', () => app.quit())
