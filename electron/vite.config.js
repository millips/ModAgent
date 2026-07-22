import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'node:module'
import path from 'node:path'
import postcss from 'postcss'

const packageInfo = createRequire(import.meta.url)('./package.json')
const edition = process.env.MODAGENT_EDITION === 'free' ? 'free' : 'subscription'

const freeCssSanitizer = () => ({
  name: 'modagent-free-css-sanitizer',
  enforce: 'pre',
  transform(code, id) {
    if (edition !== 'free' || !id.endsWith('/index.css')) return null
    const root = postcss.parse(code)
    root.walkRules(rule => {
      const selector = rule.selector || ''
      const paidSelector = /theme-technology-core|feedback-core|nav-energy-scan|app-page-atmosphere/.test(selector)
      const paidAsset = rule.nodes?.some(node =>
        node.type === 'decl' && /assets\/themes\/technology-core/.test(node.value || '')
      )
      if (paidSelector || paidAsset) rule.remove()
    })
    root.walkAtRules(atRule => {
      if (/keyframes$/i.test(atRule.name) && /^tc-/.test(atRule.params || '')) atRule.remove()
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
      source: JSON.stringify({ edition, version: packageInfo.version }),
    })
  },
})

export default defineConfig({
  root: 'src',
  plugins: [freeCssSanitizer(), react(), editionMarker()],
  define: {
    __MODAGENT_SUBSCRIPTION__: JSON.stringify(edition === 'subscription'),
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
