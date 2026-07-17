import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// Authenticate only requests to ModAgent's loopback API. Keeping this in the
// renderer avoids a session-wide Electron network hook that can stall startup.
const nativeFetch = window.fetch.bind(window)
const apiToken = window.modagent?.getApiToken?.() || ''
const exposedApiBase = window.modagent?.getApiBase?.()
const apiBase = typeof exposedApiBase === 'string' ? exposedApiBase : 'http://127.0.0.1:18890'
window.fetch = (input, init = {}) => {
  const url = typeof input === 'string' ? input : input?.url || ''
  if (url !== apiBase && !url.startsWith(apiBase + '/')) return nativeFetch(input, init)
  const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined))
  if (apiToken) headers.set('X-ModAgent-Token', apiToken)
  return nativeFetch(input, { ...init, headers })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
