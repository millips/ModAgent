import { startRenderer } from './bootstrapRuntime.mjs'

startRenderer({ load: () => import('./main.jsx') })
