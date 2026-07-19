import asyncio
import glob
import json
import os
import re
import shutil
import ssl
import tempfile
import time
import urllib.request
import urllib.error
from typing import Optional, Callable

from .config import CONFIG_DIR

DOWNLOADS_DIR = os.path.join(CONFIG_DIR, "downloads")
USER_AGENT = "ModAgent/1.0"

# 投放文件夹(靶向文件夹):放在用户数据区,给"没法自动搜/下的站"(三宫六院/3DM/网盘/私享)
# 一个统一入口——用户手动下载的 mod 扔进来,ModAgent 扫描→透视→mod_install_custom 安装。
DROPBOX_DIR = os.path.join(CONFIG_DIR, "dropbox")
TOOLS_DIR = os.path.join(CONFIG_DIR, "tools")


def ensure_downloads_dir(game_slug: str) -> str:
    path = os.path.join(DOWNLOADS_DIR, game_slug)
    os.makedirs(path, exist_ok=True)
    return path


def ensure_dropbox_dir(game_slug: str) -> str:
    path = os.path.join(DROPBOX_DIR, game_slug or "_unknown")
    os.makedirs(path, exist_ok=True)
    return path


def ensure_tools_dir() -> str:
    os.makedirs(TOOLS_DIR, exist_ok=True)
    return TOOLS_DIR


def extract_external_tool(archive_path: str, display_name: str = "") -> dict:
    """Extract a standalone modding tool into ModAgent's managed tools folder."""
    from . import installer

    archive_path = os.path.abspath(archive_path or "")
    allowed_roots = (
        os.path.abspath(DOWNLOADS_DIR),
        os.path.abspath(DROPBOX_DIR),
    )
    if not archive_path or not os.path.isfile(archive_path):
        raise FileNotFoundError(f"外部工具压缩包不存在: {archive_path}")
    if not any(
        os.path.commonpath((archive_path, root)) == root
        for root in allowed_roots
    ):
        raise RuntimeError("外部工具只允许从 ModAgent 下载缓存或投放文件夹解压")

    raw_name = display_name or os.path.splitext(os.path.basename(archive_path))[0]
    safe_name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", raw_name).strip("._")
    if not safe_name:
        safe_name = "external_tool"
    tools_root = ensure_tools_dir()
    target = os.path.abspath(os.path.join(tools_root, safe_name[:100]))
    if os.path.commonpath((target, os.path.abspath(tools_root))) != os.path.abspath(tools_root):
        raise RuntimeError("外部工具目标目录越界")

    if os.path.isdir(target):
        executables = [
            os.path.join(root, filename)
            for root, _, files in os.walk(target)
            for filename in files
            if filename.lower().endswith(".exe")
        ]
        return {
            "status": "already_extracted",
            "archive_path": archive_path,
            "tool_dir": target,
            "executables": executables[:20],
        }

    temp_dir = tempfile.mkdtemp(prefix=".extract-", dir=tools_root)
    try:
        members = installer.extract_archive(archive_path, temp_dir)
        entries = [
            entry for entry in os.listdir(temp_dir)
            if entry.lower() != "__macosx"
        ]
        source = temp_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(temp_dir, entries[0])):
            source = os.path.join(temp_dir, entries[0])
        os.replace(source, target)
        if source != temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    executables = [
        os.path.join(root, filename)
        for root, _, files in os.walk(target)
        for filename in files
        if filename.lower().endswith(".exe")
    ]
    return {
        "status": "extracted",
        "archive_path": archive_path,
        "tool_dir": target,
        "file_count": len(members),
        "executables": executables[:20],
        "note": "已解压但未自动运行可执行文件；首次启动和工具自身的游戏选择由用户确认。",
    }


# ── Preflight ──

def preflight_check(cdp_port: int, api_key: str) -> str:
    """验证 Chrome CDP + Nexus 标签页 + API Key。返回 webSocketDebuggerUrl。"""
    if not api_key:
        raise RuntimeError("未配置 Nexus API Key，请在设置中填写")

    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/list", timeout=5
        ).read())
    except Exception:
        raise RuntimeError(
            "Chrome CDP 未开启。请先启动 Chrome:\n"
            f'chrome.exe --remote-debugging-port={cdp_port} --user-data-dir="%TEMP%\\chr_cdp"'
        )

    if not isinstance(tabs, list):
        raise RuntimeError("Chrome CDP 返回异常数据")

    nexus_tab = next((t for t in tabs if "nexusmods.com" in t.get("url", "")), None)
    if not nexus_tab:
        raise RuntimeError("请在 Chrome 中打开任意 Nexus Mods 页面并登录")

    ws = nexus_tab.get("webSocketDebuggerUrl")
    if not ws:
        raise RuntimeError("无法获取 Nexus 页面的 WebSocket 调试 URL")

    return ws


# ── Step 1: 获取 file_id ──

def get_file_id(mod_id: int, game_slug: str, api_key: str, cdp_port: int = 18888):
    """从 Nexus 获取 mod 的主文件 file_id。优先 MAIN 分类。API 被拒时走 Chrome 兜底。"""
    files = _fetch_files(mod_id, game_slug, api_key, cdp_port)
    if not files:
        raise RuntimeError(f"Mod {mod_id} 没有可下载的文件（可能已被作者删除）")

    main_files = [f for f in files if f.get("category_name") == "MAIN"]
    if not main_files:
        main_files = sorted(files, key=lambda f: f.get("uploaded_timestamp", 0), reverse=True)

    if len(main_files) > 1:
        return {"variants": main_files}

    return main_files[0]["file_id"]


def _fetch_files(mod_id: int, game_slug: str, api_key: str, cdp_port: int) -> list:
    """获取 mod 文件列表；403 多为 mod 已下架/隐藏，给出精确原因。"""
    ctx = ssl._create_unverified_context()
    url = f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{mod_id}/files.json"
    req = urllib.request.Request(url, headers={
        "apikey": api_key, "Accept": "application/json", "User-Agent": USER_AGENT,
    })
    try:
        data = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
        return data.get("files", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # TLS 指纹被拦的兜底
            fid = _get_file_id_powershell(mod_id, game_slug, api_key)
            return [{"file_id": fid, "category_name": "MAIN"}]
        if e.code == 403:
            raise RuntimeError(_unavailable_reason(mod_id, game_slug, api_key))
        raise RuntimeError(f"获取文件列表失败: HTTP {e.code}")


def _unavailable_reason(mod_id: int, game_slug: str, api_key: str) -> str:
    """403 时查询 mod 状态，区分『已下架/未发布』与其他限制，返回精确说明。"""
    try:
        ctx = ssl._create_unverified_context()
        url = f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{mod_id}.json"
        req = urllib.request.Request(url, headers={
            "apikey": api_key, "Accept": "application/json", "User-Agent": USER_AGENT,
        })
        info = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
        status = info.get("status", "")
        available = info.get("available", True)
        if status and status != "published":
            return f"Mod {mod_id} 当前不可下载：状态为 {status}（available={available}）。该 Mod 很可能已被作者下架/隐藏/移入审核，请换一个 Mod。"
        if available is False:
            return f"Mod {mod_id} 已被作者设为不可用（available=False），无法下载，请换一个 Mod。"
    except Exception:
        pass
    return f"获取 Mod {mod_id} 文件列表失败: HTTP 403（可能已下架、设为私密或需要特殊权限）。"


def _get_file_id_powershell(mod_id: int, game_slug: str, api_key: str) -> int:
    """NSFW mod TLS fingerprint 被拦时，PowerShell 兜底。"""
    import subprocess
    safe_api_key = api_key.replace('"', '`"').replace("'", "`'")
    safe_slug = str(game_slug).replace('"', '').replace("'", "")
    safe_mod_id = int(mod_id)
    ps = f"""
$h = @{{"apikey"="{safe_api_key}";"Accept"="application/json"}}
$r = Invoke-RestMethod "https://api.nexusmods.com/v1/games/{safe_slug}/mods/{safe_mod_id}/files.json" -Headers $h
$m = $r.files | Where-Object {{ $_.category_name -eq "MAIN" }} | Select-Object -Last 1
Write-Output $m.file_id
"""
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell 获取 file_id 失败: {result.stderr}")
    try:
        return int(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"PowerShell 返回非数字 file_id: {result.stdout}")


def get_mod_info(mod_id: int, game_slug: str, api_key: str) -> dict:
    """从 API 获取 mod 基本信息（名称、版本）。"""
    ctx = ssl._create_unverified_context()
    url = f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{mod_id}.json"
    req = urllib.request.Request(url, headers={
        "apikey": api_key, "Accept": "application/json", "User-Agent": USER_AGENT,
    })
    data = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
    return data


# ── Step 2: 获取 CDN 直链 ──

async def get_download_url(ws_url: str, file_id: int, game_id: int) -> str:
    """在已登录的 Chrome 页面内执行 fetch，获取 CDN 直链。不导航页面，复用已有 Nexus 标签。
    ⚠️ 仅 Premium 账号可用:免费账号要求请求来自该文件的 mod 页面上下文,
    从任意标签(如首页)发起会 403。免费账号请用 get_download_url_filepage。"""
    import websockets

    expr = (
        "(async () => {"
        "  const resp = await fetch("
        "    'https://www.nexusmods.com/Core/Libs/Common/Managers/Downloads?GenerateDownloadUrl',"
        "    {"
        "      method: 'POST',"
        "      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},"
        f"      body: 'fid={file_id}&game_id={game_id}'"
        "    }"
        "  );"
        "  if (!resp.ok) return JSON.stringify({error: resp.status});"
        "  const data = await resp.json();"
        "  return JSON.stringify(data);"
        "})()"
    )

    async with websockets.connect(ws_url, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 99,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            msg = json.loads(raw)
            if msg.get("id") == 99:
                result = msg.get("result", {}).get("result", {})
                value = result.get("value") if isinstance(result, dict) else None
                if isinstance(value, str):
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        if "error" in parsed:
                            raise RuntimeError(f"GenerateDownloadUrl 失败: HTTP {parsed['error']}")
                        cdn = parsed.get("url") or parsed.get("URL")
                        if cdn:
                            return cdn
                    return value
                if isinstance(value, dict):
                    return value.get("url") or value.get("URL")
                raise RuntimeError(f"未获取到下载链接: {result}")

    raise RuntimeError("WebSocket 连接意外关闭")


def _open_tab(cdp_port: int, url: str) -> dict:
    """通过 CDP 新开标签页,返回 {id, webSocketDebuggerUrl}。新 Chrome 要求 PUT,旧版接受 GET,两者都试。"""
    import urllib.request
    endpoint = f"http://127.0.0.1:{cdp_port}/json/new?{url}"
    last = None
    for method in ("PUT", "GET"):
        try:
            req = urllib.request.Request(endpoint, method=method)
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
    raise RuntimeError(f"无法通过 CDP 新建标签页: {last}")


def _close_tab(cdp_port: int, tab_id: str) -> None:
    import urllib.request
    if not tab_id:
        return
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass


async def _cdp_eval(ws, expr: str, msg_id: int, await_promise: bool = False, timeout: float = 25):
    """在已连接的页面 ws 上执行一次 Runtime.evaluate,返回 value。"""
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": await_promise},
    }))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if msg.get("id") == msg_id:
            res = msg.get("result", {})
            exc = res.get("exceptionDetails")
            if exc:
                desc = (exc.get("exception") or {}).get("description") or exc.get("text", "")
                return {"__cdp_error__": str(desc)[:300]}
            result = res.get("result", {})
            return result.get("value") if isinstance(result, dict) else None


async def _find_captured_nexus_download(
    cdp_port: int, game_slug: str, mod_id: int
) -> str:
    """Recover a CDN URL captured after semantic browser interaction."""
    import websockets

    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{int(cdp_port)}/json/list", timeout=5
        ).read())
    except Exception:
        return ""
    marker = f"nexusmods.com/{game_slug}/mods/{int(mod_id)}"
    for tab in tabs if isinstance(tabs, list) else []:
        if marker not in str(tab.get("url", "")):
            continue
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        try:
            async with websockets.connect(
                ws_url, ping_interval=None, max_size=4 * 1024 * 1024
            ) as ws:
                value = await _cdp_eval(
                    ws, "window.__modAgentDownloadUrl || ''", 2088
                )
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
        except Exception:
            continue
    return ""


async def get_download_url_filepage(
    cdp_port: int, game_slug: str, mod_id: int, file_id: int, game_id: int
) -> str:
    """免费账号通路:专开一个标签页导航到该 mod 的文件页,在**正确的页面上下文**里
    请求 GenerateDownloadUrl(免费账号该接口校验来源页,从首页/其他页发起必 403)。
    Premium 账号走此路径同样可用。用完即关标签,不打扰用户已开的页面。

    注意:CDP 新建的标签页在导航开始前停在 about:blank,而 about:blank 的
    document.readyState 天生就是 "complete"。因此不能只等 readyState,必须以
    location.host 为准确认已真正导航到 nexusmods.com;否则 fetch 会在 about:blank
    上下文里跨源发出并被拒,CDP 序列化被拒的 Error 得到空对象,表现为 "未获取到下载链接: {}"。
    """
    import websockets

    page_url = f"https://www.nexusmods.com/{game_slug}/mods/{mod_id}?tab=files&file_id={file_id}"
    captured = await _find_captured_nexus_download(cdp_port, game_slug, mod_id)
    if captured:
        return captured

    tab = _open_tab(cdp_port, page_url)
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        _close_tab(cdp_port, tab.get("id", ""))
        raise RuntimeError("新标签页缺少 webSocketDebuggerUrl(Chrome 需以 --remote-debugging-port 启动)")

    try:
        async with websockets.connect(ws_url, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
            # ── 等待真正落到 nexusmods.com 且 DOM 可用(最长 30s)──
            probe = None
            for i in range(60):
                probe = await _cdp_eval(ws, "location.host + '|' + document.readyState", 1000 + i)
                if (isinstance(probe, str) and "nexusmods.com" in probe
                        and not probe.endswith("|loading")):
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError(f"文件页导航超时(最后状态: {probe!r});页面可能未加载或被重定向")

            expr = (
                "(async () => { try {"
                "  const resp = await fetch("
                "    'https://www.nexusmods.com/Core/Libs/Common/Managers/Downloads?GenerateDownloadUrl',"
                "    {"
                "      method: 'POST',"
                "      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',"
                "                'X-Requested-With': 'XMLHttpRequest'},"
                f"      body: 'fid={file_id}&game_id={game_id}'"
                "    }"
                "  );"
                "  if (!resp.ok) return JSON.stringify({error: resp.status});"
                "  const txt = await resp.text();"
                "  try { JSON.parse(txt); } catch(_) {"
                "    return JSON.stringify({bad_body: txt.slice(0, 200), at: location.href});"
                "  }"
                "  return txt;"
                "} catch(e) {"
                "  return JSON.stringify({js_error: String(e), at: location.href});"
                "} })()"
            )

            # ── fetch 允许重试:页面就绪但站方 session 尚未完全初始化时,给它几秒 ──
            last_err = None
            for attempt in range(3):
                value = await _cdp_eval(ws, expr, 99 + attempt, await_promise=True)

                if isinstance(value, dict) and "__cdp_error__" in value:
                    last_err = f"CDP 执行异常: {value['__cdp_error__']}"
                    await asyncio.sleep(3)
                    continue

                parsed = None
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                    except Exception:
                        parsed = None
                elif isinstance(value, dict):
                    parsed = value

                if isinstance(parsed, dict):
                    if "js_error" in parsed:
                        last_err = f"页面内 fetch 异常: {parsed['js_error']} @ {parsed.get('at', '')}"
                        await asyncio.sleep(3)
                        continue
                    if "bad_body" in parsed:
                        last_err = (f"GenerateDownloadUrl 返回非 JSON @ {parsed.get('at', '')}: "
                                    f"{parsed['bad_body']!r}(疑似登录态失效或站方改版)")
                        await asyncio.sleep(3)
                        continue
                    if "error" in parsed:
                        raise RuntimeError(
                            f"GenerateDownloadUrl 失败: HTTP {parsed['error']}"
                            f"(已在文件页上下文内请求;若持续 403,请在浏览器中打开该 mod 的"
                            f" Files 页手动点一次 Slow download 通过站方校验后重试)")
                    cdn = parsed.get("url") or parsed.get("URL")
                    if cdn:
                        return cdn

                last_err = (
                    f"未获取到下载链接(原始返回: {value!r})。"
                    "参数正确时返回 [] 多为站方临时风控(C-4 实测:数分钟后自愈),"
                    "请等 1-2 分钟重试;或在浏览器打开该 mod 的 Files 页手动点一次"
                    " Slow download 后再试。"
                )
                await asyncio.sleep(3)

            raise RuntimeError(last_err or "未获取到下载链接: 未知原因")
    finally:
        _close_tab(cdp_port, tab.get("id", ""))


# ── Step 3: 下载文件 ──

def download_file(url: str, local_path: str, progress_callback: Optional[Callable] = None):
    """下载 CDN 直链，支持断点续传 + 完整性校验。
    限速/断流导致中途中断时，用 HTTP Range 从断点续传，下完核对总大小，不完整不入库。"""
    if not url or url == 'None':
        raise RuntimeError("下载链接无效，请重试")

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    ctx = ssl._create_unverified_context()
    tmp_path = local_path + ".part"

    downloaded = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    total = None
    stall = 0  # 连续无进展次数

    for attempt in range(12):
        headers = {"User-Agent": USER_AGENT}
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=120)
        except Exception as e:
            stall += 1
            if stall >= 5:
                raise RuntimeError(f"下载失败（已重试 {stall} 次）: {e}")
            time.sleep(2)
            continue

        status = getattr(resp, "status", 200)
        # 服务器忽略 Range（返回 200 而非 206）→ 从头开始
        if downloaded and status == 200:
            downloaded = 0
        # 确定总大小
        if total is None:
            cr = resp.headers.get("Content-Range", "")
            if "/" in cr:
                try:
                    total = int(cr.split("/")[-1])
                except ValueError:
                    total = None
            if total is None:
                clen = int(resp.headers.get("Content-Length", 0))
                total = (clen + downloaded) if (downloaded and status == 206) else clen

        mode = "ab" if downloaded else "wb"
        got = 0
        with open(tmp_path, mode) as f:
            while True:
                try:
                    chunk = resp.read(65536)
                except Exception:
                    break
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                got += len(chunk)
                if progress_callback and total:
                    progress_callback(min(downloaded / total, 1.0))
        try:
            resp.close()
        except Exception:
            pass

        if total and downloaded >= total:
            break
        if not total:
            break  # 无法判断总量，按一次性完成处理
        # 没下完 → 续传
        if got == 0:
            stall += 1
            if stall >= 5:
                raise RuntimeError(f"下载停滞，不完整: {downloaded}/{total} 字节")
            time.sleep(2)
        else:
            stall = 0
    else:
        raise RuntimeError(f"下载重试次数用尽，不完整: {downloaded}/{total}")

    size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    if size == 0:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError("下载文件为空，请重试")
    if total and size < total:
        raise RuntimeError(f"下载不完整: {size}/{total} 字节，请重试")

    os.replace(tmp_path, local_path)
    return local_path


# ── Step 4: 依赖解析（CDP 抓页面） ──

async def get_requirements(ws_url: str, mod_id: int, game_slug: str) -> list[int]:
    """从 mod 描述页 DT/DD 结构解析官方 Requirements。"""
    import websockets

    expr = (
        "(async () => {"
        f"  const resp = await fetch('https://www.nexusmods.com/{game_slug}/mods/{mod_id}?tab=description');"
        "  const html = await resp.text();"
        "  const parser = new DOMParser();"
        "  const doc = parser.parseFromString(html, 'text/html');"
        "  const reqs = [];"
        "  const dts = doc.querySelectorAll('dt');"
        "  for (const dt of dts) {"
        "    if (dt.textContent.trim().includes('equire')) {"
        "      let el = dt.nextElementSibling;"
        "      while (el && el.tagName !== 'DT') {"
        "        if (el.tagName === 'DD') {"
        "          const links = el.querySelectorAll('a[href*=\"/mods/\"]');"
        "          for (const a of links) {"
        "            const m = a.href.match(/mods\\/(\\d+)/);"
        f"            if (m) reqs.push(parseInt(m[1]));"
        "          }"
        "        }"
        "        el = el.nextElementSibling;"
        "      }"
        "      break;"
        "    }"
        "  }"
        f"  return JSON.stringify([...new Set(reqs)].filter(id => id !== {mod_id}));"
        "})()"
    )

    async with websockets.connect(ws_url, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 2, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
        }))

        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 2:
                result = msg.get("result", {}).get("result", {})
                value = result.get("value") if isinstance(result, dict) else None
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        pass
                if isinstance(value, list):
                    return value
                return []


# ── CDP 辅助 ──

def _find_nexus_ws(cdp_port: int) -> Optional[str]:
    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/list", timeout=5
        ).read())
        for tab in tabs:
            if "nexusmods.com" in tab.get("url", ""):
                return tab.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None


async def fetch_mod_page_cdp(mod_id: int, game_slug: str, cdp_port: int = 18888) -> Optional[dict]:
    """API 403/401 时，用已登录的 Chrome 抓取 mod 页面解析基础信息（成人内容兜底）。"""
    import websockets

    ws_url = _find_nexus_ws(cdp_port)
    if not ws_url:
        return None

    expr = (
        "(async () => {"
        f"  const resp = await fetch('https://www.nexusmods.com/{game_slug}/mods/{mod_id}');"
        "  if (!resp.ok) return JSON.stringify({error: resp.status});"
        "  const html = await resp.text();"
        "  const doc = new DOMParser().parseFromString(html, 'text/html');"
        "  const pick = (s,a) => { const el = doc.querySelector(s); return el ? ((a ? el.getAttribute(a) : el.textContent) || '').trim() : ''; };"
        "  let name = pick('meta[property=\"og:title\"]','content') || pick('#pagetitle .header');"
        "  name = name.replace(/ at .*$/i,'').trim();"
        "  const summary = pick('meta[name=\"description\"]','content');"
        "  let version = '';"
        "  const sv = doc.querySelector('.stat-version .stat');"
        "  if (sv) version = sv.textContent.trim();"
        "  const dc = doc.querySelector('#mod_description_container');"
        "  const description = (dc ? dc.textContent : summary).trim().slice(0,2000);"
        f"  return JSON.stringify({{mod_id: {mod_id}, name, summary, version, description}});"
        "})()"
    )

    try:
        async with websockets.connect(ws_url, ping_interval=None, max_size=8 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "id": 7, "method": "Runtime.evaluate",
                "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
            }))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                msg = json.loads(raw)
                if msg.get("id") == 7:
                    result = msg.get("result", {}).get("result", {})
                    value = result.get("value") if isinstance(result, dict) else None
                    if isinstance(value, str):
                        try:
                            d = json.loads(value)
                            if isinstance(d, dict) and not d.get("error") and d.get("name"):
                                return d
                        except json.JSONDecodeError:
                            pass
                    return None
    except Exception:
        return None


async def fetch_collection_cdp(slug: str, cdp_port: int = 18888) -> Optional[dict]:
    """用已登录 Chrome 调 Nexus GraphQL，读取合集(Collection)里包含的全部 mod。"""
    import websockets

    ws_url = _find_nexus_ws(cdp_port)
    if not ws_url:
        return None

    query = ("query C($slug: String!) { collection(slug: $slug, viewAdultContent: true) "
             "{ name latestPublishedRevision { modCount modFiles { file { mod { modId name summary } } } } } }")
    payload = json.dumps({"query": query, "variables": {"slug": slug}})
    body_js = json.dumps(payload)  # 作为 JS 字符串字面量安全注入

    expr = (
        "(async () => {"
        f"  const r = await fetch('https://api.nexusmods.com/v2/graphql', {{method:'POST', credentials:'include', headers:{{'Content-Type':'application/json'}}, body: {body_js} }});"
        "  if (!r.ok) return JSON.stringify({error: r.status});"
        "  return await r.text();"
        "})()"
    )

    try:
        async with websockets.connect(ws_url, ping_interval=None, max_size=16 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "id": 9, "method": "Runtime.evaluate",
                "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
            }))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=25)
                msg = json.loads(raw)
                if msg.get("id") == 9:
                    val = msg.get("result", {}).get("result", {}).get("value")
                    if not isinstance(val, str):
                        return None
                    data = json.loads(val)
                    coll = (data.get("data") or {}).get("collection")
                    if not coll:
                        return None
                    rev = coll.get("latestPublishedRevision") or {}
                    mods, seen = [], set()
                    for mf in rev.get("modFiles", []):
                        mod = (((mf or {}).get("file") or {}).get("mod") or {})
                        mid = mod.get("modId")
                        if mid and mid not in seen:
                            seen.add(mid)
                            mods.append({"mod_id": mid, "name": mod.get("name", ""), "summary": mod.get("summary", "")})
                    return {"name": coll.get("name", ""), "mod_count": rev.get("modCount", len(mods)), "mods": mods}
    except Exception:
        return None


# ── 完整下载流程 ──

async def download_mod(
    mod_id: int,
    game_slug: str,
    game_id: int,
    api_key: str,
    cdp_port: int = 18888,
    progress_callback: Optional[Callable] = None,
    file_id: Optional[int] = None,
) -> dict:
    """完整下载一个 mod 的标准流程（按 SOP）。传入 file_id 可直接下载指定变体。"""
    # 0. 检查本地缓存 — 命中直接返回，不要求开 Chrome
    cache_pattern = os.path.join(DOWNLOADS_DIR, game_slug, f"{mod_id}_*.zip")
    cached = glob.glob(cache_pattern)
    if cached and not file_id:
        return {"mod_id": mod_id, "local_path": cached[0], "cached": True}

    # 1. 前置检查 — 真要下载才需要 Chrome
    ws_url = preflight_check(cdp_port, api_key)

    # 2. 获取 file_id（未指定时自动解析；指定则跳过，直接下载该变体）
    if file_id is None:
        file_id_result = get_file_id(mod_id, game_slug, api_key, cdp_port)

        # 3. 处理多变体
        if isinstance(file_id_result, dict) and "variants" in file_id_result:
            return {"variants": file_id_result["variants"], "mod_id": mod_id}

        file_id = file_id_result

    # 4. 获取 mod 信息（名称、版本）
    try:
        info = get_mod_info(mod_id, game_slug, api_key)
        mod_name = info.get("name", f"mod_{mod_id}")
        version = info.get("version", "latest")
    except Exception:
        mod_name = f"mod_{mod_id}"
        version = "latest"

    # 5+6. 下载（每次尝试都生成全新直链以打败 TTL/死链；download_file 跨尝试断点续传；
    #       下完做解压完整性校验，满大小但损坏则删掉重下）
    safe_name = mod_name.replace(" ", "_").replace("/", "_").replace("\\", "_")[:60]
    filename = f"{mod_id}_{safe_name}_v{version}.zip"
    local_path = os.path.join(DOWNLOADS_DIR, game_slug, filename)

    last_err = None
    for attempt in range(6):
        # 每次都重新生成直链（旧链可能已过期）。
        # 走"文件页上下文"通路:免费账号必须如此(从首页等其他页请求必 403),Premium 同样兼容。
        try:
            cdn_url = await get_download_url_filepage(cdp_port, game_slug, mod_id, file_id, game_id)
        except RuntimeError as e:
            last_err = e
            # get_download_url_filepage 已在同一个标签内重试三次。继续外层循环
            # 只会反复开 Files 页，并不能修复登录、参数或站方确认问题。
            raise RuntimeError(
                f"下载 mod {mod_id} 失败: {e}"
            ) from e
        if not cdn_url or cdn_url == 'None':
            last_err = RuntimeError("获取下载链接失败")
            await asyncio.sleep(2)
            continue

        try:
            download_file(cdn_url, local_path, progress_callback)  # 内部断点续传 + 字节完整性校验
        except Exception as e:
            last_err = e  # 链接中途失效/断流 → 保留 .part，下次用新链续传
            await asyncio.sleep(2)
            continue

        # 字节完整 → 再验解压完整性（抓"满大小但内部损坏"）
        if _verify_archive(local_path):
            return {
                "mod_id": mod_id, "file_id": file_id, "local_path": local_path,
                "cached": False, "mod_name": mod_name, "version": version,
            }
        # 损坏 → 删掉（含 .part）重新整下
        last_err = RuntimeError("压缩包完整性校验失败")
        for p in (local_path, local_path + ".part"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        await asyncio.sleep(2)

    raise RuntimeError(f"下载 mod {mod_id} 失败（已自动重试多次）: {last_err}")


def _verify_archive(path: str) -> bool:
    """校验压缩包完整性。优先用 7-Zip（兼容 zip/rar/7z 及非标准 zip）。"""
    try:
        from . import installer
        sz = installer._find_7zip()
        if sz:
            import subprocess
            r = subprocess.run([sz, "t", path], capture_output=True, text=True, timeout=180)
            return r.returncode == 0
        # 无 7-Zip：尽力验 zip
        import zipfile
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return z.testzip() is None
    except Exception:
        return False
    return True  # 无法验证时不误删


# ── 搜索（CDP 抓搜索结果页） ──

async def search_via_cdp(query: str, game_slug: str, game_id: int, cdp_port: int = 18888) -> list[dict]:
    """搜索 Nexus Mods 通过 Chrome CDP（在搜索框输入 + 提取结果）。"""
    import websockets
    import urllib.parse

    ws_url = _find_nexus_ws(cdp_port)
    if not ws_url:
        return []

    async with websockets.connect(ws_url, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 0, "method": "Page.enable"}))
        await ws.recv()

        # Navigate to mods page
        await ws.send(json.dumps({"id": 1, "method": "Page.navigate",
            "params": {"url": f"https://www.nexusmods.com/games/{game_slug}/mods"}}))
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 1: break

        await asyncio.sleep(4)

        # Simulate typing in search box and submitting
        search_expr = f"""
        (async () => {{
            // Find the search input — try multiple selectors
            let input = document.querySelector('input[type="search"], input[placeholder*="search" i], input[placeholder*="Search"], [class*="SearchInput"] input, form[class*="search"] input, #search');
            if (!input) {{
                const all = document.querySelectorAll('input');
                for (const el of all) {{
                    if (el.type === 'search' || (el.placeholder||'').toLowerCase().includes('search') || (el.name||'').toLowerCase().includes('search') || el.id === 'search') {{
                        input = el; break;
                    }}
                }}
            }}
            if (!input) return JSON.stringify({{error: 'no_search_input', inputs: document.querySelectorAll('input').length}});

            // Use native setter to set value
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, '{query}');
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            input.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', keyCode: 13, bubbles: true}}));

            return JSON.stringify({{ok: true, desc: input.placeholder || input.type || input.id || 'search'}});
        }})()
        """
        await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
            "params": {"expression": search_expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 2: break

        await asyncio.sleep(4)

        # Extract results from the rendered page
        extract_expr = """
        (async () => {
            const tiles = document.querySelectorAll('[data-e2eid="mod-tile-title"]');
            const results = [];
            const seen = new Set();
            for (const a of tiles) {
                const m = a.href.match(/mods\\/(\\d+)/);
                const name = a.textContent.trim();
                if (m && !seen.has(m[1]) && name) {
                    seen.add(m[1]);
                    results.push({mod_id: parseInt(m[1]), name: name.substring(0, 80)});
                }
            }
            return JSON.stringify(results);
        })()
        """
        await ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
            "params": {"expression": extract_expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == 3:
                result = msg.get("result", {}).get("result", {})
                value = result.get("value") if isinstance(result, dict) else None
                if isinstance(value, str):
                    try: return json.loads(value)
                    except: pass
                if isinstance(value, list): return value
                return []
