import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'node:module'
import path from 'node:path'
import postcss from 'postcss'

const packageInfo = createRequire(import.meta.url)('./package.json')
const edition = process.env.MODAGENT_EDITION === 'subscription' ? 'subscription' : 'free'
const channel = process.env.MODAGENT_CHANNEL === 'beta' ? 'beta' : 'stable'

const freeCssSanitizer = () => ({
  name: 'modagent-free-css-sanitizer',
  enforce: 'pre',
  transform(code, id) {
    if (edition !== 'free' || !id.endsWith('/index.css')) return null
    const root = postcss.parse(code)
    root.walkRules(rule => {
      const selector = rule.selector || ''
      const paidSelector = /theme-technology-core|theme-classic-controls|theme-minimal-tech|feedback-core|nav-energy-scan|nav-kawaii|app-page-atmosphere|body\[data-ma-theme|body\[data-ma-lighting/.test(selector)
      const paidAsset = rule.nodes?.some(node =>
        node.type === 'decl' && /assets\/themes\//.test(node.value || '')
      )
      if (paidSelector || paidAsset) rule.remove()
    })
    root.walkAtRules(atRule => {
      if (
        /keyframes$/i.test(atRule.name) &&
        /^(?:tc-|kawaii-|cat-|gothic-|tactical-|abyssal-)/.test(atRule.params || '')
      ) atRule.remove()
    })
    return { code: root.toString(), map: null }
  },
})

const editionMarker = () => ({
  name: 'modagent-edition-marker',
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'edition.json',
      source: JSON.stringify({ edition, channel, version: packageInfo.version }),
    })
  },
})

export default defineConfig({
  root: 'src',
  plugins: [freeCssSanitizer(), react(), editionMarker()],
  define: {
    __MODAGENT_SUBSCRIPTION__: JSON.stringify(edition === 'subscription'),
    __MODAGENT_VERSION__: JSON.stringify(packageInfo.version),
  },
  resolve: {
    alias: {
      '@edition': path.resolve(
        __dirname,
        edition === 'subscription'
          ? 'src/edition/subscription.jsx'
          : 'src/edition/free.jsx'
      ),
    },
  },
  base: './',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
})
