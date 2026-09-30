import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import ChatPage from '../../src/components/ChatPage.jsx'
window.fixture = { calls: [], toasts: [], refreshes: 0 }
window.fetch = async (url) => {
  window.fixture.calls.push(String(url))
  const data = String(url).endsWith('/sessions') ? []
    : String(url).endsWith('/tool/scan_existing_mods')
      ? { result: JSON.stringify({ identified: [], imported: 0, detected: 129 }) } : {}
  return { ok: true, json: async () => data }
}
function Fixture() {
  const [count, setCount] = useState(0)
  return <><output id="inventory-count">{count}</output><ChatPage api="https://fixture.invalid" games={[]}
    status={{ online: true, game_slug: 'fixture', game_name: 'Fixture', installed_mods: count }}
    toast={(message)=>window.fixture.toasts.push(message)}
    onRefresh={()=>{window.fixture.refreshes++; setCount(97)}} /></>
}
createRoot(document.getElementById('root')).render(<Fixture />)
