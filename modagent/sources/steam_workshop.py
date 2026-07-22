"""Steam 创意工坊适配器（CDP 路线）：
- 从游戏目录解析 Steam AppID
- 用已登录的 Chrome 标签页搜索工坊、订阅/取消订阅
- 订阅后 Steam 客户端自动把内容下到 steamapps/workshop/content/<appid>/<id>/
工坊是平台托管，安装=订阅，卸载=取消订阅。需要：Steam 客户端在运行 + 浏览器登录 Steam。"""
import asyncio
import glob
import json
import os
import re
import urllib.request


# ── AppID 与工坊目录 ──

def resolve_appid(game_root: str):
    """从 <库>/steamapps/appmanifest_*.acf 里按 installdir 匹配，拿到 AppID。"""
    steamapps = os.path.dirname(os.path.dirname(game_root))  # <库>/steamapps
    folder = os.path.basename(game_root.rstrip("\\/"))
    for acf in glob.glob(os.path.join(steamapps, "appmanifest_*.acf")):
        try:
            with open(acf, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        m_dir = re.search(r'"installdir"\s+"([^"]+)"', text)
        if m_dir and m_dir.group(1).lower() == folder.lower():
            m_id = re.search(r'"appid"\s+"(\d+)"', text)
            if m_id:
                return int(m_id.group(1))
    return None


def workshop_content_dir(game_root: str, appid: int) -> str:
    steamapps = os.path.dirname(os.path.dirname(game_root))
    return os.path.join(steamapps, "workshop", "content", str(appid))


def get_titles(ids: list) -> dict:
    """批量查工坊物品标题（公开 API，无需 key/登录）。返回 {id: title}。"""
    import ssl
    out = {}
    ids = [re.sub(r"\D", "", str(i)) for i in ids if str(i).strip()]
    ctx = ssl._create_unverified_context()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        body = ("itemcount=" + str(len(chunk)) + "&" +
                "&".join(f"publishedfileids%5B{j}%5D={pid}" for j, pid in enumerate(chunk))).encode()
        try:
            req = urllib.request.Request(
                "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
                data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
            data = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
            for d in data.get("response", {}).get("publishedfiledetails", []):
                pid = str(d.get("publishedfileid", ""))
                if pid and d.get("title"):
                    out[pid] = d["title"]
        except Exception:
            continue
    return out


# ── CDP：找到已登录的 Steam 标签页 ──

def _steam_ws(cdp_port: int):
    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/list", timeout=5).read())
        for t in tabs:
            if "steamcommunity.com" in t.get("url", ""):
                return t.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None


async def _eval(ws_url: str, expr: str, timeout: int = 25):
    import websockets
    async with websockets.connect(ws_url, ping_interval=None, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if msg.get("id") == 1:
                res = msg.get("result", {}).get("result", {})
                return res.get("value") if isinstance(res, dict) else None


# ── 搜索 ──

async def search(query: str, appid: int, cdp_port: int = 18888) -> list:
    """在已登录的 Steam 标签页内 fetch 工坊浏览页并解析（同源，无需 API key）。"""
    ws_url = _steam_ws(cdp_port)
    if not ws_url:
        raise RuntimeError("未找到已登录的 Steam 标签页，请在 ModAgent 打开的浏览器中登录 steamcommunity.com")
    q = (query or "").replace("'", "")
    expr = (
        "(async () => {"
        f"  const url = 'https://steamcommunity.com/workshop/browse/?appid={appid}&searchtext='"
        f"    + encodeURIComponent('{q}') + '&browsesort=textsearch&actualsort=textsearch&p=1';"
        "  const r = await fetch(url, {credentials:'include'});"
        "  const html = await r.text();"
        "  const doc = new DOMParser().parseFromString(html, 'text/html');"
        "  const out = []; const seen = new Set();"
        "  for (const a of doc.querySelectorAll('a[href*=\"filedetails/?id=\"]')) {"
        "    const m = a.href.match(/id=(\\d+)/); if (!m || seen.has(m[1])) continue;"
        "    const img = a.querySelector('img'); const name = img ? (img.alt||'').trim() : '';"
        "    if (!name) continue;"  # 没标题的多为导航/装饰链接，跳过
        "    seen.add(m[1]);"
        "    out.push({id: m[1], name: name.slice(0,80), url: 'https://steamcommunity.com/sharedfiles/filedetails/?id='+m[1]});"
        "    if (out.length >= 20) break;"
        "  }"
        "  return JSON.stringify(out);"
        "})()"
    )
    val = await _eval(ws_url, expr)
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return []
    return val or []


# ── 订阅 / 取消订阅 ──

async def _sub_action(action: str, pubfileid: str, appid: int, cdp_port: int) -> dict:
    ws_url = _steam_ws(cdp_port)
    if not ws_url:
        raise RuntimeError("未找到已登录的 Steam 标签页，请在 ModAgent 打开的浏览器中登录 steamcommunity.com")
    pid = re.sub(r"\D", "", str(pubfileid))
    expr = (
        "(async () => {"
        "  const sid = (typeof g_sessionID!=='undefined' && g_sessionID) || (document.cookie.match(/sessionid=([^;]+)/)||[])[1];"
        "  if (!sid) return JSON.stringify({error:'no_session', hint:'请确认已登录 Steam'});"
        f"  const r = await fetch('https://steamcommunity.com/sharedfiles/{action}', {{"
        "    method:'POST', credentials:'include',"
        "    headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},"
        f"    body: 'id={pid}&appid={appid}&sessionid=' + encodeURIComponent(sid)"
        "  });"
        "  let body=''; try { body = await r.text(); } catch(e) {}"
        "  return JSON.stringify({status:r.status, ok:r.ok, body: body.slice(0,200)});"
        "})()"
    )
    val = await _eval(ws_url, expr)
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return {"error": "bad_response"}
    return val or {"error": "no_response"}


async def subscribe(pubfileid: str, appid: int, cdp_port: int = 18888) -> dict:
    return await _sub_action("subscribe", pubfileid, appid, cdp_port)


async def unsubscribe(pubfileid: str, appid: int, cdp_port: int = 18888) -> dict:
    return await _sub_action("unsubscribe", pubfileid, appid, cdp_port)


# ── 等待 Steam 客户端下载完成 ──

async def wait_for_download(game_root: str, appid: int, pubfileid: str, timeout: int = 120, progress_callback=None) -> dict:
    """订阅后 Steam 客户端会下载到 workshop/content/<appid>/<id>/，轮询确认。"""
    pid = re.sub(r"\D", "", str(pubfileid))
    target = os.path.join(workshop_content_dir(game_root, appid), pid)
    waited = 0
    while waited < timeout:
        if os.path.isdir(target) and any(os.scandir(target)):
            files = [os.path.join(r, f) for r, _, fs in os.walk(target) for f in fs]
            size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
            return {"downloaded": True, "path": target, "files": files, "size": size}
        if progress_callback:
            progress_callback(min(waited / timeout, 0.95))
        await asyncio.sleep(2)
        waited += 2
    return {"downloaded": False, "path": target, "files": []}
