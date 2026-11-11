import React, { useEffect, useRef, useState } from 'react'
import { Globe, RefreshCw, CheckCircle2, AlertCircle, Clock } from 'lucide-react'

const STATUS = {
  reachable: ['可连接（HTTP）', 'Connected (HTTP)', 'green'],
  redirect: ['收到重定向', 'Redirect received', 'amber'],
  auth_required: ['需要身份验证', 'Authentication required', 'amber'],
  restricted: ['站点拒绝访问', 'Access restricted', 'amber'],
  proxy_auth: ['代理需要认证', 'Proxy authentication required', 'amber'],
  rate_limited: ['请求被限流', 'Rate limited', 'amber'],
  service_error: ['站点或网关异常', 'Site or gateway error', 'amber'],
  http_error: ['HTTP 响应异常', 'Unexpected HTTP response', 'amber'],
  timeout: ['连接超时', 'Timed out', 'red'],
  dns_error: ['域名解析失败', 'DNS lookup failed', 'red'],
  tls_error: ['证书或 TLS 错误', 'Certificate or TLS error', 'red'],
  proxy_error: ['代理连接失败', 'Proxy connection failed', 'red'],
  configuration_error: ['连接配置异常', 'Connection configuration error', 'red'],
  connection_error: ['连接失败', 'Connection failed', 'red'],
  api_error: ['本地诊断服务失败', 'Local diagnostic service failed', 'red'],
  busy: ['已有测试正在运行', 'A test is already running', 'amber'],
}
const HINT = {
  reachable: ['仅验证此地址的 HTTP 响应，未验证搜索、登录或文件下载。', 'Only this URL responded. Search, login and file downloads were not tested.'],
  redirect: ['地址可响应；未跟随跳转，尚未验证目标页面。', 'The URL responded. The redirect destination was not tested.'],
  auth_required: ['已收到 HTTP 401；此测试不发送账户凭据。', 'HTTP 401 received. This test does not send account credentials.'],
  restricted: ['已收到 HTTP 403，可能需要浏览器验证或被站点限制，不能据此判定被墙。', 'HTTP 403 received. Browser verification or site restrictions may apply; this does not prove a network block.'],
  proxy_auth: ['检查代理认证设置。', 'Check your proxy authentication settings.'],
  rate_limited: ['稍后重试，避免连续点击。', 'Wait before retrying; avoid repeated requests.'],
  service_error: ['服务或中间网关已响应错误，稍后重试。', 'The service or an intermediate gateway returned an error. Retry later.'],
  http_error: ['已收到响应，但此地址暂不可正常使用。', 'A response was received, but the URL is not available normally.'],
  timeout: ['8 秒内未完成连接。检查网络或已有代理后重测。', 'No completed response within 8 seconds. Check your connection or existing proxy and retry.'],
  dns_error: ['检查网络与 DNS 设置后重测。', 'Check your network and DNS settings, then retry.'],
  tls_error: ['检查系统时间、证书与代理；请勿关闭证书校验。', 'Check your clock, certificates and proxy. Keep certificate verification enabled.'],
  proxy_error: ['确认已有代理正在运行且端口可访问。', 'Check that your existing proxy is running and its port is reachable.'],
  configuration_error: ['检查代理地址、协议及所需依赖。', 'Check the proxy URL, protocol and required dependencies.'],
  connection_error: ['检查连接或已有代理。浏览器与应用的线路可能不同。', 'Check your connection or existing proxy. Browser and app routes may differ.'],
  api_error: ['本地后端未完成诊断；这不是目标网站的测试结果。', 'The local backend did not finish the test. This is not a result for the target website.'],
  busy: ['等待现有测试结束后重试。', 'Wait for the current test to finish, then retry.'],
}

function readTargets(payload) {
  if (!Array.isArray(payload?.targets) || !payload.targets.length || payload.targets.length > 32) throw new Error('invalid_targets')
  const ids = new Set()
  return payload.targets.map(target => {
    if (!target || typeof target.id !== 'string' || !/^[a-z][a-z0-9_]{0,31}$/.test(target.id)
      || ['constructor', 'prototype', '__proto__'].includes(target.id) || ids.has(target.id)
      || typeof target.name !== 'string' || !target.name.trim() || typeof target.url !== 'string') throw new Error('invalid_target')
    const url = new URL(target.url)
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('invalid_url')
    ids.add(target.id)
    return { ...target, hostname: url.hostname }
  })
}

function validResult(result, id) {
  return result?.target_id === id && Object.hasOwn(STATUS, result.status)
    && Number.isFinite(result.elapsed_ms) && result.elapsed_ms >= 0
    && (result.http_status === null || (Number.isInteger(result.http_status) && result.http_status >= 100 && result.http_status <= 599))
    && typeof result.checked_at === 'string' && Number.isFinite(Date.parse(result.checked_at))
}

export default function ConnectionTestPanel({ api, language = 'zh-CN' }) {
  const en = language === 'en'
  const [targets, setTargets] = useState([])
  const [results, setResults] = useState({})
  const [running, setRunning] = useState(new Set())
  const [allBusy, setAllBusy] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)
  const active = useRef(new Set())
  const batch = useRef(false)
  const controllers = useRef(new Set())
  const loadGeneration = useRef(0)
  const text = (zh, english) => en ? english : zh

  async function request(path, options = {}) {
    const controller = new AbortController()
    controllers.current.add(controller)
    const timer = setTimeout(() => controller.abort(), 12000)
    try {
      const response = await fetch(api + path, { ...options, signal: controller.signal })
      // Keep the deadline and unmount cancellation active until JSON is read,
      // not merely until response headers arrive.
      const payload = response.ok ? await response.json() : null
      return { ok: response.ok, status: response.status, payload }
    } finally {
      clearTimeout(timer)
      controllers.current.delete(controller)
    }
  }

  async function loadTargets() {
    const generation = ++loadGeneration.current
    const current = () => alive.current && generation === loadGeneration.current
    setLoading(true)
    setLoadError(false)
    try {
      const response = await request('/network/targets')
      if (!response.ok) throw new Error('local_api')
      const items = readTargets(response.payload)
      if (current()) setTargets(items)
    } catch (_) {
      if (current()) { setTargets([]); setLoadError(true) }
    } finally {
      if (current()) setLoading(false)
    }
  }

  useEffect(() => {
    alive.current = true
    loadTargets()
    return () => {
      alive.current = false
      loadGeneration.current++
      for (const controller of controllers.current) controller.abort()
    }
  }, [api])

  async function testOne(id) {
    if (!alive.current || active.current.has(id)) return
    active.current.add(id)
    setRunning(new Set(active.current))
    setResults(old => { const next = { ...old }; delete next[id]; return next })
    try {
      const response = await request('/network/test', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: id }),
      })
      if (response.status === 409) {
        if (alive.current) setResults(old => ({ ...old, [id]: { status: 'busy' } }))
        return
      }
      if (!response.ok) throw new Error('local_api')
      const result = response.payload
      if (!validResult(result, id)) throw new Error('invalid_result')
      if (alive.current) setResults(old => ({ ...old, [id]: result }))
    } catch (_) {
      if (alive.current) setResults(old => ({ ...old, [id]: { status: 'api_error' } }))
    } finally {
      active.current.delete(id)
      if (alive.current) setRunning(new Set(active.current))
    }
  }

  async function testAll() {
    if (batch.current || active.current.size || !targets.length) return
    batch.current = true
    setAllBusy(true)
    setResults({})
    const queue = targets.map(item => item.id)
    try {
      await Promise.all(Array.from({ length: 3 }, async () => {
        while (queue.length && alive.current) await testOne(queue.shift())
      }))
    } finally {
      batch.current = false
      if (alive.current) setAllBusy(false)
    }
  }

  return <section className="card-cyber space-y-3" aria-label={text('连接测试', 'Connection test')}>
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-medium flex items-center gap-2"><Globe size={15} className="text-cyber-cyan" />{text('连接测试', 'Connection test')}</h3>
      <button type="button" className="btn-cyber text-xs flex items-center gap-1.5 disabled:opacity-50"
        disabled={loading || loadError || allBusy || running.size > 0} onClick={testAll}>
        <RefreshCw size={13} className={allBusy ? 'animate-spin' : ''} />{allBusy ? text('测试中…', 'Testing…') : text('测试全部', 'Test all')}
      </button>
    </div>
    <p className="text-xs text-slate-400 leading-relaxed">{text(
      '使用应用后端当前的 HTTP 代理设置，只测试公开地址，不发送 API Key 或 Cookie，也不调用模型。浏览器、搜索与下载可能使用不同线路。',
      'Uses the backend HTTP client’s current proxy settings. Public URLs only; no API keys, cookies or model calls. Browser, search and download routes may differ.')}</p>
    {loading && <p className="text-xs">{text('正在读取测试项目…', 'Loading test targets…')}</p>}
    {loadError && <div role="alert" className="text-xs text-red-400 flex items-center gap-3">
      <span>{text('无法读取本地诊断服务。', 'Cannot reach the local diagnostic service.')}</span>
      <button type="button" className="btn-ghost" onClick={loadTargets}>{text('重试', 'Retry')}</button>
    </div>}
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {targets.map(target => {
        const result = results[target.id]
        const busy = running.has(target.id)
        const waiting = allBusy && !busy && !result
        const status = result && STATUS[result.status]
        const color = busy || !status ? 'text-slate-400' : status[2] === 'green' ? 'text-emerald-400' : status[2] === 'amber' ? 'text-amber-400' : 'text-red-400'
        const Icon = busy ? RefreshCw : !status ? Clock : status[2] === 'green' ? CheckCircle2 : AlertCircle
        return <article key={target.id} data-connection-target={target.id} className="rounded-lg border border-surface-600 p-3 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{target.name}</span>
            <button type="button" className="btn-ghost text-slate-300 p-1 disabled:opacity-40" disabled={busy || allBusy}
              aria-label={text('测试 ', 'Test ') + target.name} onClick={() => testOne(target.id)}>
              <RefreshCw size={14} className={busy ? 'animate-spin' : ''} />
            </button>
          </div>
          <p className="text-[10px] text-slate-400 break-all mt-1">{target.hostname}</p>
          <p role="status" className={`text-xs flex items-center gap-1.5 mt-2 ${color}`}>
            <Icon size={13} className={busy ? 'animate-spin' : ''} />
            {busy ? text('测试中…', 'Testing…') : waiting ? text('等待测试', 'Queued') : status ? status[en ? 1 : 0] : text('待检测', 'Not tested')}
          </p>
          {result && <>
            <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">{HINT[result.status]?.[en ? 1 : 0]}</p>
            <div className="text-[10px] text-slate-400 mt-2 border-t border-surface-600 pt-2 flex flex-wrap gap-x-2">
              {Number.isFinite(result.elapsed_ms) && <span>{result.elapsed_ms} ms</span>}
              {result.http_status && <span>HTTP {result.http_status}</span>}
              {result.checked_at && <time dateTime={result.checked_at}>{new Date(result.checked_at).toLocaleString(en ? 'en-US' : 'zh-CN')}</time>}
            </div>
          </>}
        </article>
      })}
    </div>
    <p className="text-[11px] text-slate-400">{text('更换网络或代理后请重新测试。耗时是 HTTP 响应时间，不是下载速度。', 'Retest after changing your network or proxy. Timing measures the HTTP response, not download speed.')}</p>
  </section>
}
