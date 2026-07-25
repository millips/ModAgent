"""Semantic Chrome CDP tools for the ModAgent LLM.

These tools expose what the browser actually renders instead of forcing the
model to infer page state from a fixed SOP.  They are deliberately restricted
to known mod-distribution domains and return compact semantic snapshots rather
than raw HTML.
"""

import asyncio
import json
import time
import urllib.parse
import urllib.request
from typing import Optional

from . import playwright_driver

ALLOWED_HOST_SUFFIXES = (
    "nexusmods.com",
    "steamcommunity.com",
    "github.com",
    "githubusercontent.com",
    "thunderstore.io",
    "gamebanana.com",
    "moddb.com",
    "curseforge.com",
    "fluffyquack.com",
    "loverslab.com",
    "patreon.com",
    "deviantart.com",
    "3dmgame.com",
    "sglynp.com",
    "mod.io",
    "itch.io",
)

_TAB_HANDLES: dict[str, str] = {}
_NEXT_TAB_HANDLE = 1
_TARGET_HINTS: dict[tuple[str, str], dict] = {}


def _stable_handle(tab_id: str) -> str:
    global _NEXT_TAB_HANDLE
    for handle, current_id in _TAB_HANDLES.items():
        if current_id == tab_id:
            return handle
    handle = f"tab-{_NEXT_TAB_HANDLE}"
    _NEXT_TAB_HANDLE += 1
    _TAB_HANDLES[handle] = tab_id
    return handle


def _allowed_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme in {"http", "https"}
            and any(host == suffix or host.endswith("." + suffix)
                    for suffix in ALLOWED_HOST_SUFFIXES)
        )
    except Exception:
        return False


def _tabs(cdp_port: int) -> list[dict]:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{int(cdp_port)}/json/list", timeout=5
    ) as response:
        tabs = json.loads(response.read().decode("utf-8"))
    return [
        tab for tab in tabs
        if tab.get("type") == "page" and _allowed_url(tab.get("url", ""))
    ]


def list_pages(cdp_port: int) -> dict:
    try:
        tabs = _tabs(cdp_port)
    except Exception as exc:
        return {
            "status": "browser_unavailable",
            "error": str(exc),
            "pages": [],
        }
    return {
        "status": "ok",
        "pages": [
            {
                "tab_id": tab.get("id"),
                "stable_id": _stable_handle(tab.get("id", "")),
                "title": tab.get("title", ""),
                "url": tab.get("url", ""),
            }
            for tab in tabs
        ],
    }


def _select_tab(cdp_port: int, tab_id: str = "") -> dict:
    tabs = _tabs(cdp_port)
    if tab_id:
        resolved_id = _TAB_HANDLES.get(tab_id, tab_id)
        match = next((tab for tab in tabs if tab.get("id") == resolved_id), None)
        if not match:
            raise RuntimeError("指定页面不存在、已关闭或不属于允许的 Mod 站点")
        return match
    if not tabs:
        raise RuntimeError("ModAgent 浏览器中没有已打开的受支持 Mod 站点页面")
    # Chrome's /json/list normally returns the most recently active page first.
    return tabs[0]


async def _evaluate(tab: dict, expression: str, await_promise: bool = False):
    import websockets

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("页面缺少 CDP WebSocket 地址")
    async with websockets.connect(
        ws_url, ping_interval=None, max_size=8 * 1024 * 1024
    ) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        }))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if message.get("id") != 1:
                continue
            result = message.get("result", {})
            if result.get("exceptionDetails"):
                detail = result["exceptionDetails"]
                raise RuntimeError(
                    (detail.get("exception") or {}).get("description")
                    or detail.get("text")
                    or "页面脚本执行失败"
                )
            return result.get("result", {}).get("value")


async def _native_click(
    tab: dict, target_id: str, target_hint: Optional[dict] = None,
) -> dict:
    """Click at the rendered element's centre using trusted CDP mouse events."""
    import websockets

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("页面缺少 CDP WebSocket 地址")
    safe_target = json.dumps(str(target_id))
    safe_hint = json.dumps(target_hint or {}, ensure_ascii=False)
    prepare = f"""
    (() => {{
      const id = {safe_target};
      const hint = {safe_hint};
      const findDeep = root => {{
        const direct = root.querySelector?.(`[data-modagent-target="${{CSS.escape(id)}}"]`);
        if (direct) return direct;
        for (const node of root.querySelectorAll?.('*') || []) {{
          if (node.shadowRoot) {{
            const found = findDeep(node.shadowRoot);
            if (found) return found;
          }}
        }}
        return null;
      }};
      let el = findDeep(document);
      if (!el && (hint.text || hint.href)) {{
        const visible = node => {{
          const r = node.getBoundingClientRect();
          const s = getComputedStyle(node);
          return r.width > 0 && r.height > 0 &&
            s.display !== 'none' && s.visibility !== 'hidden';
        }};
        const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
        const candidates = [];
        const visit = root => {{
          if (!root?.querySelectorAll) return;
          for (const node of root.querySelectorAll(
            'a[href],button,input,[role="button"],[role="link"]'
          )) {{
            if (visible(node)) candidates.push(node);
            if (node.shadowRoot) visit(node.shadowRoot);
          }}
          for (const node of root.querySelectorAll('*')) {{
            if (node.shadowRoot) visit(node.shadowRoot);
          }}
        }};
        visit(document);
        const exactHref = candidates.filter(node =>
          hint.href && String(node.href || '') === String(hint.href)
        );
        const exactText = candidates.filter(node =>
          hint.text && clean(
            node.innerText || node.value || node.getAttribute('aria-label')
          ) === clean(hint.text)
        );
        const ranked = (exactHref.length ? exactHref : exactText).sort(
          (a, b) => Number(!!b.closest(
            '[role="dialog"],dialog,.modal,[class*="modal"]'
          )) - Number(!!a.closest(
            '[role="dialog"],dialog,.modal,[class*="modal"]'
          ))
        );
        if (ranked.length === 1 || (hint.href && exactHref.length >= 1)) {{
          el = ranked[0];
        }}
      }}
      if (!el) return {{status:'target_missing', target_id:id}};
      if (el.disabled || el.getAttribute('aria-disabled') === 'true')
        return {{status:'target_disabled', target_id:id}};
      const label = String(el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
      if (/(delete|remove|purchase|buy now|subscribe|unsubscribe|upload|publish|post|send message|删除|购买|订阅|退订|上传|发布)/i.test(label))
        return {{status:'dangerous_action_blocked', target_id:id, label}};
      el.scrollIntoView({{block:'center', inline:'center'}});
      const r = el.getBoundingClientRect();
      return {{
        status:'ready', target_id:id, label,
        x:r.left + r.width / 2, y:r.top + r.height / 2,
        before_url:location.href
      }};
    }})()
    """

    async with websockets.connect(
        ws_url, ping_interval=None, max_size=8 * 1024 * 1024
    ) as ws:
        async def command(message_id: int, method: str, params: dict):
            await ws.send(json.dumps({
                "id": message_id, "method": method, "params": params,
            }))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if message.get("id") == message_id:
                    return message.get("result", {})

        prepared_result = await command(1, "Runtime.evaluate", {
            "expression": prepare, "returnByValue": True,
        })
        prepared = prepared_result.get("result", {}).get("value")
        if not isinstance(prepared, dict) or prepared.get("status") != "ready":
            return prepared or {"status": "target_prepare_failed"}
        point = {"x": prepared["x"], "y": prepared["y"], "button": "left"}
        await command(2, "Input.dispatchMouseEvent", {
            **point, "type": "mouseMoved",
        })
        await command(3, "Input.dispatchMouseEvent", {
            **point, "type": "mousePressed", "clickCount": 1,
        })
        await command(4, "Input.dispatchMouseEvent", {
            **point, "type": "mouseReleased", "clickCount": 1,
        })
        prepared["status"] = "clicked"
        prepared["trusted_event"] = True
        return prepared


_OBSERVE_SCRIPT = r"""
(() => {
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  if (!window.__modAgentDownloadCaptureInstalled) {
    window.__modAgentDownloadCaptureInstalled = true;
    window.__modAgentDownloadUrl = window.__modAgentDownloadUrl || '';
    const capture = value => {
      try {
        const data = typeof value === 'string' ? JSON.parse(value) : value;
        const item = Array.isArray(data) ? data[0] : data;
        const url = item && (item.url || item.URL);
        if (url) window.__modAgentDownloadUrl = url;
      } catch (_) {}
    };
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
      const response = await originalFetch.apply(this, args);
      try {
        if (/GenerateDownloadUrl/i.test(String(args[0]))) {
          capture(await response.clone().text());
        }
      } catch (_) {}
      return response;
    };
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
      this.__modAgentUrl = String(url || '');
      return originalOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args) {
      if (/GenerateDownloadUrl/i.test(this.__modAgentUrl || '')) {
        this.addEventListener('load', () => capture(this.responseText), {once:true});
      }
      return originalSend.apply(this, args);
    };
  }
  const visible = el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || 1) > 0;
  };
  const selector = 'a[href],button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]';
  const deepElements = root => {
    const found = [];
    const visit = node => {
      if (!node?.querySelectorAll) return;
      for (const el of node.querySelectorAll('*')) {
        found.push(el);
        if (el.shadowRoot) visit(el.shadowRoot);
      }
    };
    visit(root);
    return found;
  };
  const allNodes = deepElements(document);
  allNodes.filter(el => el.hasAttribute?.('data-modagent-target'))
    .forEach(el => el.removeAttribute('data-modagent-target'));
  const observationId = (window.__modAgentObservationId || 0) + 1;
  window.__modAgentObservationId = observationId;
  const main = document.querySelector('main,[role="main"],article,#mainContent,#main-content,.page-content,[class*="PageContent"]');
  const score = el => {
    const label = clean(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title'));
    let value = 0;
    if (el.closest('[role="dialog"],dialog,.modal,[class*="modal"]')) value += 100;
    if (main && main.contains(el)) value += 40;
    if (/manual|slow download|download|continue|search|files|login|sign in/i.test(label)) value += 80;
    if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') value += 15;
    return value;
  };
  const elements = allNodes.filter(el => el.matches?.(selector))
    .filter(visible)
    .sort((a, b) => score(b) - score(a))
    .slice(0, 180);
  elements.forEach((el, index) =>
    el.setAttribute('data-modagent-target', `ma-${observationId}-${index + 1}`)
  );
  const controls = elements.map(el => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const text = clean(
      el.innerText || el.value || el.getAttribute('aria-label') ||
      el.getAttribute('title') || el.getAttribute('placeholder')
    ).slice(0, 240);
    return {
      target_id: el.getAttribute('data-modagent-target'),
      kind: tag === 'a' ? 'link' : (tag === 'input' || tag === 'textarea' || tag === 'select') ? 'input' : 'button',
      text,
      type,
      href: tag === 'a' ? el.href : '',
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
    };
  });
  const dialogs = allNodes.filter(el =>
      el.matches?.('[role="dialog"],dialog,.modal,[class*="modal"]'))
    .filter(visible)
    .map(el => clean(el.innerText).slice(0, 2000))
    .filter(Boolean)
    .slice(0, 8);
  const headings = [...document.querySelectorAll('h1,h2,h3')]
    .filter(visible).map(el => clean(el.innerText)).filter(Boolean).slice(0, 30);
  const alerts = [...document.querySelectorAll('[role="alert"],.alert,.error,[class*="error"],[class*="warning"]')]
    .filter(visible).map(el => clean(el.innerText)).filter(Boolean).slice(0, 20);
  const mainText = clean(main?.innerText).slice(0, 12000);
  const bodyText = mainText ? '' : clean(document.body?.innerText).slice(0, 8000);
  const capturedDownload = window.__modAgentDownloadUrl || '';
  const resources = performance.getEntriesByType('resource').map(x => x.name)
    .filter(x => /download|nexus-cdn|cf-files/i.test(x)).slice(-20);
  return {
    status: 'ok',
    url: location.href,
    title: document.title,
    ready_state: document.readyState,
    headings,
    dialogs,
    alerts,
    controls,
    main_text: mainText,
    body_text: bodyText,
    captured_download_url: capturedDownload,
    recent_download_resources: resources
  };
})()
"""


def observe(cdp_port: int, tab_id: str = "") -> dict:
    try:
        tab = _select_tab(cdp_port, tab_id)
        result = asyncio.run(_evaluate(tab, _OBSERVE_SCRIPT))
        if not isinstance(result, dict):
            raise RuntimeError("页面观察返回了异常数据")
        result["tab_id"] = tab.get("id")
        result["stable_id"] = _stable_handle(tab.get("id", ""))
        for control in result.get("controls", []):
            target_id = control.get("target_id")
            if target_id:
                _TARGET_HINTS[(tab.get("id", ""), target_id)] = dict(control)
        if len(_TARGET_HINTS) > 1200:
            for key in list(_TARGET_HINTS)[:400]:
                _TARGET_HINTS.pop(key, None)
        enhanced = playwright_driver.aria_snapshot(
            cdp_port, result.get("url", ""), result.get("title", "")
        )
        if enhanced.get("status") == "ok":
            result["aria_snapshot"] = enhanced.get("aria_snapshot", "")
            result["driver"] = "playwright+cdp"
        else:
            result["driver"] = "cdp-fallback"
        return result
    except Exception as exc:
        return {"status": "observe_failed", "error": str(exc)}


def click(cdp_port: int, target_id: str, tab_id: str = "") -> dict:
    try:
        tab = _select_tab(cdp_port, tab_id)
        before_tabs = {item.get("id") for item in _tabs(cdp_port)}
        result = playwright_driver.click(
            cdp_port, tab.get("url", ""), target_id, tab.get("title", "")
        )
        if result.get("status") in {
            "unavailable", "page_not_found", "failed",
            "target_missing", "target_ambiguous",
        }:
            hint = _TARGET_HINTS.get((tab.get("id", ""), target_id))
            result = asyncio.run(_native_click(tab, target_id, hint))
        time.sleep(0.8)
        after_tabs = _tabs(cdp_port)
        new_tabs = [item for item in after_tabs if item.get("id") not in before_tabs]
        target_tab_id = new_tabs[0].get("id") if new_tabs else tab.get("id")
        snapshot = observe(cdp_port, target_tab_id)
        if snapshot.get("status") == "observe_failed" and after_tabs:
            snapshot = observe(cdp_port, after_tabs[0].get("id", ""))
        return {"action": result, "page": snapshot}
    except Exception as exc:
        return {"status": "click_failed", "error": str(exc)}


def input_text(
    cdp_port: int, target_id: str, value: str,
    tab_id: str = "", submit: bool = False,
) -> dict:
    safe_target = json.dumps(str(target_id))
    safe_value = json.dumps(str(value))
    submit_js = "true" if submit else "false"
    script = f"""
    (() => {{
      const id = {safe_target};
      const value = {safe_value};
      const findDeep = root => {{
        const direct = root.querySelector?.(`[data-modagent-target="${{CSS.escape(id)}}"]`);
        if (direct) return direct;
        for (const node of root.querySelectorAll?.('*') || []) {{
          if (node.shadowRoot) {{
            const found = findDeep(node.shadowRoot);
            if (found) return found;
          }}
        }}
        return null;
      }};
      const el = findDeep(document);
      if (!el) return {{status:'target_missing', target_id:id}};
      const type = String(el.type || '').toLowerCase();
      const autocomplete = String(el.autocomplete || '').toLowerCase();
      if (type === 'password' || /password|cc-|one-time-code/.test(autocomplete))
        return {{status:'sensitive_input_blocked', target_id:id}};
      el.focus();
      const proto = el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(el, value); else el.value = value;
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.dispatchEvent(new Event('change', {{bubbles:true}}));
      if ({submit_js}) {{
        el.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', code:'Enter', keyCode:13, bubbles:true}}));
        el.form?.requestSubmit?.();
      }}
      return {{status:'input_set', target_id:id, submitted:{submit_js}}};
    }})()
    """
    try:
        tab = _select_tab(cdp_port, tab_id)
        result = playwright_driver.input_text(
            cdp_port, tab.get("url", ""), target_id, value,
            title=tab.get("title", ""), submit=submit,
        )
        if result.get("status") in {
            "unavailable", "page_not_found", "failed"
        }:
            result = asyncio.run(_evaluate(tab, script))
        time.sleep(0.8 if submit else 0.2)
        snapshot = observe(cdp_port, tab.get("id"))
        return {"action": result, "page": snapshot}
    except Exception as exc:
        return {"status": "input_failed", "error": str(exc)}


def wait_and_observe(
    cdp_port: int, seconds: float = 1, tab_id: str = "",
    text: str = "", url_pattern: str = "", timeout_ms: int = 10000,
) -> dict:
    tab = _select_tab(cdp_port, tab_id)
    if text or url_pattern:
        wait_result = playwright_driver.wait_for(
            cdp_port, tab.get("url", ""), text=text,
            url_pattern=url_pattern, timeout_ms=timeout_ms,
        )
    else:
        delay = max(0.2, min(float(seconds or 1), 10.0))
        time.sleep(delay)
        wait_result = {"status": "delay_complete", "seconds": delay}
    return {"wait": wait_result, "page": observe(cdp_port, tab.get("id", ""))}


def doctor(cdp_port: int) -> dict:
    started = time.monotonic()
    try:
        pages = list_pages(cdp_port)
        version_url = f"http://127.0.0.1:{int(cdp_port)}/json/version"
        with urllib.request.urlopen(version_url, timeout=5) as response:
            version = json.loads(response.read().decode("utf-8"))
        return {
            "status": "ok",
            "preferred_driver": "playwright",
            "fallback_driver": "raw-cdp",
            "cdp": {
                "connected": True,
                "browser": version.get("Browser", ""),
                "pages": len(pages.get("pages", [])),
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
            "playwright": playwright_driver.doctor(cdp_port),
        }
    except Exception as exc:
        return {
            "status": "browser_unavailable",
            "error": str(exc),
            "playwright": playwright_driver.doctor(cdp_port),
        }


def open_page(cdp_port: int, url: str) -> dict:
    if not _allowed_url(url):
        return {
            "status": "blocked_domain",
            "error": "只允许打开受支持的 Mod 分发站点",
        }
    try:
        normalized = urllib.parse.urlsplit(url)._replace(fragment="").geturl()
        for existing in _tabs(cdp_port):
            existing_url = urllib.parse.urlsplit(
                existing.get("url", "")
            )._replace(fragment="").geturl()
            if existing_url == normalized:
                result = observe(cdp_port, existing.get("id", ""))
                result["reused_tab"] = True
                return result
        endpoint = f"http://127.0.0.1:{int(cdp_port)}/json/new?{url}"
        request = urllib.request.Request(endpoint, method="PUT")
        with urllib.request.urlopen(request, timeout=8) as response:
            tab = json.loads(response.read().decode("utf-8"))
        time.sleep(1)
        return observe(cdp_port, tab.get("id", ""))
    except Exception as exc:
        return {"status": "open_failed", "error": str(exc)}
