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


ALLOWED_HOST_SUFFIXES = (
    "nexusmods.com",
    "steamcommunity.com",
    "github.com",
    "githubusercontent.com",
    "thunderstore.io",
    "gamebanana.com",
    "mod.io",
    "itch.io",
)


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
                "title": tab.get("title", ""),
                "url": tab.get("url", ""),
            }
            for tab in tabs
        ],
    }


def _select_tab(cdp_port: int, tab_id: str = "") -> dict:
    tabs = _tabs(cdp_port)
    if tab_id:
        match = next((tab for tab in tabs if tab.get("id") == tab_id), None)
        if not match:
            raise RuntimeError("指定页面不存在、已关闭或不属于允许的 Mod 站点")
        return match
    if not tabs:
        raise RuntimeError("Chrome 中没有已打开的受支持 Mod 站点页面")
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


async def _native_click(tab: dict, target_id: str) -> dict:
    """Click at the rendered element's centre using trusted CDP mouse events."""
    import websockets

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("页面缺少 CDP WebSocket 地址")
    safe_target = json.dumps(str(target_id))
    prepare = f"""
    (() => {{
      const id = {safe_target};
      const el = document.querySelector(`[data-modagent-target="${{CSS.escape(id)}}"]`);
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
  const visible = el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || 1) > 0;
  };
  const selector = 'a[href],button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]';
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
  const elements = [...document.querySelectorAll(selector)]
    .filter(visible)
    .sort((a, b) => score(b) - score(a))
    .slice(0, 180);
  elements.forEach((el, index) => el.setAttribute('data-modagent-target', `ma-${index + 1}`));
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
  const dialogs = [...document.querySelectorAll('[role="dialog"],dialog,.modal,[class*="modal"]')]
    .filter(visible)
    .map(el => clean(el.innerText).slice(0, 2000))
    .filter(Boolean)
    .slice(0, 8);
  const headings = [...document.querySelectorAll('h1,h2,h3')]
    .filter(visible).map(el => clean(el.innerText)).filter(Boolean).slice(0, 30);
  const alerts = [...document.querySelectorAll('[role="alert"],.alert,.error,[class*="error"],[class*="warning"]')]
    .filter(visible).map(el => clean(el.innerText)).filter(Boolean).slice(0, 20);
  const mainText = clean(main?.innerText).slice(0, 16000);
  const bodyText = clean(document.body?.innerText).slice(0, 5000);
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
        return result
    except Exception as exc:
        return {"status": "observe_failed", "error": str(exc)}


def click(cdp_port: int, target_id: str, tab_id: str = "") -> dict:
    try:
        tab = _select_tab(cdp_port, tab_id)
        result = asyncio.run(_native_click(tab, target_id))
        time.sleep(0.8)
        snapshot = observe(cdp_port, tab.get("id"))
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
      const el = document.querySelector(`[data-modagent-target="${{CSS.escape(id)}}"]`);
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
        result = asyncio.run(_evaluate(tab, script))
        time.sleep(0.8 if submit else 0.2)
        snapshot = observe(cdp_port, tab.get("id"))
        return {"action": result, "page": snapshot}
    except Exception as exc:
        return {"status": "input_failed", "error": str(exc)}


def wait_and_observe(cdp_port: int, seconds: float, tab_id: str = "") -> dict:
    delay = max(0.2, min(float(seconds or 1), 10.0))
    time.sleep(delay)
    return observe(cdp_port, tab_id)


def open_page(cdp_port: int, url: str) -> dict:
    if not _allowed_url(url):
        return {
            "status": "blocked_domain",
            "error": "只允许打开受支持的 Mod 分发站点",
        }
    try:
        endpoint = f"http://127.0.0.1:{int(cdp_port)}/json/new?{url}"
        request = urllib.request.Request(endpoint, method="PUT")
        with urllib.request.urlopen(request, timeout=8) as response:
            tab = json.loads(response.read().decode("utf-8"))
        time.sleep(1)
        return observe(cdp_port, tab.get("id", ""))
    except Exception as exc:
        return {"status": "open_failed", "error": str(exc)}
