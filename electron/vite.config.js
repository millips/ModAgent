import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'node:module'

const packageInfo = createRequire(import.meta.url)('./package.json')
const edition = packageInfo.modagentEdition || 'unknown'

const editionMarker = () => ({
  name: 'modagent-edition-marker',
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'edition.json',
      source: JSON.stringify({ edition, version: packageInfo.version }),
    })
  },
})

export default defineConfig({
  root: 'src',
  plugins: [react(), editionMarker()],
  base: './',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
})
