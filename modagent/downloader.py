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
import urllib.parse
from pathlib import Path
from typing import Optional, Callable

from .config import CONFIG_DIR
from . import task_control
from . import progress

DOWNLOADS_DIR = os.path.join(CONFIG_DIR, "downloads")
USER_AGENT = "ModAgent/1.0"

# 投放文件夹(靶向文件夹):放在用户数据区,给"没法自动搜/下的站"(三宫六院/3DM/网盘/私享)
# 一个统一入口——用户手动下载的 mod 扔进来,ModAgent 扫描→透视→mod_install_custom 安装。
DROPBOX_DIR = os.path.join(CONFIG_DIR, "dropbox")
TOOLS_DIR = os.path.join(CONFIG_DIR, "tools")
STALE_ARCHIVE_DAYS = 7
STALE_PART_DAYS = 1
MAX_CACHE_BYTES = 2 * 1024 * 1024 * 1024


class NexusManualDownloadRequired(RuntimeError):
    """Nexus requires login, consent, or verification that cannot be automated."""

    def __init__(
        self, page_url: str, reason: str = "", existing_gate: bool = False,
        diagnostics: Optional[dict] = None,
    ):
        self.page_url = page_url
        self.reason = reason
        self.existing_gate = existing_gate
        self.diagnostics = diagnostics or {}
        super().__init__(
            "该 Nexus 文件需要页面确认，页面已保留；其他文件仍可继续处理。"
            f"{reason}"
        )


class NexusDirectDownloadUnavailable(RuntimeError):
    """The official API could identify the file but did not issue a CDN URL."""

    def __init__(self, message: str, diagnostics: Optional[dict] = None):
        self.diagnostics = diagnostics or {}
        super().__init__(message)


class DownloadFailure(RuntimeError):
    """A classified download failure that callers can handle deterministically."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: str,
        retryable: bool,
        attempts: int,
        http_status: Optional[int] = None,
    ):
        self.failure_kind = failure_kind
        self.retryable = retryable
        self.attempts = attempts
        self.http_status = http_status
        self.terminal = not retryable
        super().__init__(message)

    def as_dict(self) -> dict:
        return {
            "failure_kind": self.failure_kind,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "attempts": self.attempts,
            "http_status": self.http_status,
        }


_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _raise_if_download_cancelled() -> None:
    task_control.raise_if_cancelled()
    if progress.is_cancel_requested():
        raise task_control.TaskCancelled(
            "用户已取消当前下载；不会继续重试或执行后续安装。"
        )


def _classify_download_error(exc: Exception) -> tuple[str, bool, Optional[int]]:
    """Return (kind, retryable, HTTP status) without exposing signed URLs."""
    if isinstance(exc, urllib.error.HTTPError):
        status = int(exc.code)
        if status in _TRANSIENT_HTTP_STATUS:
            return "http_transient", True, status
        if status in {401, 403}:
            return "http_access_denied", False, status
        if status in {404, 410}:
            return "http_not_found", False, status
        return "http_client_error" if 400 <= status < 500 else "http_error", False, status
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return "network_transient", True, None
    return "unknown", False, None


def _download_failure_message(
    kind: str,
    attempts: int,
    status: Optional[int] = None,
) -> str:
    if kind == "http_not_found":
        return (
            f"下载地址不存在或已失效（HTTP {status}），未继续重试。"
            "请重新解析来源页面或选择仍然存在的 Release 资产。"
        )
    if kind == "http_access_denied":
        return (
            f"下载地址拒绝访问（HTTP {status}），未继续重试。"
            "请检查登录、权限或重新生成下载链接。"
        )
    if kind == "http_client_error":
        return f"下载请求无效（HTTP {status}），未继续重试。请重新核验下载来源。"
    if kind == "http_transient":
        return f"下载服务暂时不可用（HTTP {status}），连续尝试 {attempts} 次后已停止。"
    if kind == "network_transient":
        return f"网络连接连续失败 {attempts} 次，已停止本轮自动重试；稍后可手动重试。"
    return "下载遇到不可识别的终止性错误，已停止自动重试。"


_NEXUS_MANUAL_GATES: dict[str, dict] = {}
_NEXUS_MANUAL_GATE_SECONDS = 30


def _nexus_files_page_url(
    game_slug: str, mod_id: int, file_id: int = 0,
) -> str:
    """Open the Files tab while preserving the exact selected file identity."""
    url = f"https://www.nexusmods.com/{game_slug}/mods/{int(mod_id)}?tab=files"
    if int(file_id or 0) > 0:
        url += f"&file_id={int(file_id)}"
    return url


def _nexus_gate_reason(state: dict, automated_stage: str = "") -> str:
    """Describe the observed gate without calling a signed-in user logged out."""
    if automated_stage == "target-file-control-ambiguous":
        return (
            "Nexus 文件页同时存在多个版本按钮，页面没有把目标 file_id "
            "唯一关联到可点击控件；为避免下载错版本，已跳过当前项"
        )
    if automated_stage in {"no-progress", "timeout"}:
        return "Nexus 页面自动流程未产生新状态，已停止当前项的页面操作"
    if state.get("siteDownloadError"):
        return (
            "（Nexus 页面自身未生成下载位置："
            f"{state['siteDownloadError']}；这不是登录状态错误）"
        )
    if state.get("login") and not state.get("loggedIn"):
        return "（检测到 Nexus 尚未登录）"
    if state.get("adult"):
        return "（需要确认成人内容显示权限）"
    if state.get("captcha"):
        return "（检测到站方人机验证）"
    return (
        "（已自动尝试 Files → Manual Download → Slow Download，"
        "但站方页面尚未产生下载链接；"
        f"页面状态：{state or automated_stage}）"
    )


def ensure_downloads_dir(game_slug: str) -> str:
    path = os.path.join(DOWNLOADS_DIR, game_slug)
    os.makedirs(path, exist_ok=True)
    return path


def _download_meta_path(path: str) -> str:
    return path + ".modagent.json"


def _remember_download(path: str, game_slug: str, mod_id: int, file_id) -> None:
    """持久记录 Nexus 文件身份，让指定 file_id 的重试也能准确命中缓存。"""
    remember_download_provenance(path, {
        "source": "nexus",
        "game_slug": game_slug,
        "source_key": str(mod_id),
        "mod_id": str(mod_id),
        "file_id": str(file_id or ""),
    })


def remember_download_provenance(path: str, metadata: dict) -> None:
    """Persist verified source identity beside a ModAgent-owned archive."""
    path = os.path.abspath(str(path or ""))
    if (
        not path
        or not isinstance(metadata, dict)
        or not any(_inside(path, root) for root in managed_cache_roots())
    ):
        return
    payload = {
        str(key): value
        for key, value in metadata.items()
        if key in {
            "source", "game_slug", "source_key", "source_url",
            "name", "version", "mod_id", "file_id", "dependencies",
            "updated_at", "detail_verified", "verification_source",
            "deprecated", "staleness",
        }
        and value not in (None, "")
    }
    try:
        with open(_download_meta_path(path), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


def read_download_provenance(path: str) -> dict:
    """Read provenance only from ModAgent-owned caches."""
    path = os.path.abspath(str(path or ""))
    if not path or not any(_inside(path, root) for root in managed_cache_roots()):
        return {}
    try:
        with open(_download_meta_path(path), encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def find_cached_nexus_download(game_slugs, mod_id, file_id=None) -> str:
    """跨本地/Nexus slug 查缓存；指定 file_id 时只复用同一变体。"""
    if isinstance(game_slugs, str):
        game_slugs = [game_slugs]
    for bucket in dict.fromkeys(str(s) for s in (game_slugs or []) if s):
        pattern = os.path.join(DOWNLOADS_DIR, bucket, f"{mod_id}_*.zip")
        for path in sorted(glob.glob(pattern)):
            if not os.path.isfile(path):
                continue
            if file_id is None:
                return path
            try:
                with open(_download_meta_path(path), encoding="utf-8") as f:
                    meta = json.load(f)
                if (str(meta.get("mod_id")) == str(mod_id)
                        and str(meta.get("file_id")) == str(file_id)):
                    return path
            except (OSError, ValueError, TypeError):
                continue
    return ""


def ensure_dropbox_dir(game_slug: str) -> str:
    path = os.path.join(DROPBOX_DIR, game_slug or "_unknown")
    os.makedirs(path, exist_ok=True)
    return path


def managed_cache_roots() -> list[str]:
    """Caches owned by ModAgent; deliberately excludes the user dropbox."""
    data_root = os.path.dirname(os.path.abspath(DOWNLOADS_DIR))
    return [
        os.path.abspath(DOWNLOADS_DIR),
        os.path.join(data_root, "browser-downloads"),
    ]


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.normcase(os.path.realpath(path)),
             os.path.normcase(os.path.realpath(root))]
        ) == os.path.normcase(os.path.realpath(root))
    except ValueError:
        return False


def cleanup_installed_archive(archive_path: str) -> dict:
    """Delete an archive only after installation and only from owned caches."""
    path = os.path.abspath(str(archive_path or ""))
    if not path or not os.path.isfile(path):
        return {"removed": False, "reason": "not_found"}
    if not any(_inside(path, root) for root in managed_cache_roots()):
        return {"removed": False, "reason": "user_managed_file"}
    try:
        size = os.path.getsize(path)
        os.remove(path)
        try:
            os.remove(_download_meta_path(path))
        except OSError:
            pass
        return {"removed": True, "bytes_freed": size, "path": path}
    except OSError as exc:
        return {"removed": False, "reason": str(exc), "path": path}


def cleanup_stale_downloads(
    now: float | None = None,
    archive_days: int = STALE_ARCHIVE_DAYS,
    part_days: int = STALE_PART_DAYS,
    max_bytes: int = MAX_CACHE_BYTES,
) -> dict:
    """Bound cache age and size without touching files outside owned roots."""
    now = time.time() if now is None else now
    entries = []
    orphan_metadata = []
    for root in managed_cache_roots():
        if not os.path.isdir(root):
            continue
        for current, _, files in os.walk(root):
            for filename in files:
                path = os.path.join(current, filename)
                if filename.lower().endswith(".modagent.json"):
                    archive_path = path[:-len(".modagent.json")]
                    if not os.path.isfile(archive_path):
                        try:
                            os.remove(path)
                            orphan_metadata.append(path)
                        except OSError:
                            pass
                        continue
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                entries.append({
                    "path": path,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "part": filename.lower().endswith(".part"),
                })

    removed = []
    kept = []
    for item in entries:
        limit_days = part_days if item["part"] else archive_days
        if now - item["mtime"] > limit_days * 86400:
            try:
                os.remove(item["path"])
                removed.append(item)
            except OSError:
                kept.append(item)
        else:
            kept.append(item)

    total = sum(item["size"] for item in kept)
    if total > max_bytes:
        for item in sorted(kept, key=lambda value: value["mtime"]):
            if total <= max_bytes:
                break
            try:
                os.remove(item["path"])
                total -= item["size"]
                removed.append(item)
            except OSError:
                continue
    removed_dirs = 0
    for root in managed_cache_roots():
        if not os.path.isdir(root):
            continue
        for current, dirs, _ in os.walk(root, topdown=False):
            for dirname in dirs:
                path = os.path.join(current, dirname)
                try:
                    os.rmdir(path)
                    removed_dirs += 1
                except OSError:
                    pass
    return {
        "removed_files": len(removed) + len(orphan_metadata),
        "bytes_freed": sum(item["size"] for item in removed),
        "remaining_bytes": total,
        "orphan_metadata_removed": len(orphan_metadata),
        "empty_directories_removed": removed_dirs,
    }


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
    """验证 Chromium CDP + Nexus 标签页 + API Key。返回 WebSocket URL。"""
    if not api_key:
        raise RuntimeError("未配置 Nexus API Key，请在设置中填写")

    try:
        tabs = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json/list", timeout=5
        ).read())
    except Exception:
        raise RuntimeError(
            "浏览器自动化服务未启动。ModAgent 支持 Microsoft Edge、"
            "Google Chrome 和 Brave；请重启 ModAgent 后重试。"
        )

    if not isinstance(tabs, list):
        raise RuntimeError("浏览器 CDP 返回异常数据")

    nexus_tab = next((t for t in tabs if "nexusmods.com" in t.get("url", "")), None)
    if not nexus_tab:
        raise RuntimeError("请在 ModAgent 打开的浏览器中打开 Nexus Mods 页面并登录")

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

def get_download_url_api(
    game_slug: str, mod_id: int, file_id: int, api_key: str,
) -> str:
    """Ask the official Nexus API for a signed CDN URL.

    This is the clean direct path for accounts entitled to API downloads.
    Free accounts commonly receive 403 and must continue through the website;
    that expected refusal is preserved as structured diagnostics.
    """
    url = (
        f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{int(mod_id)}"
        f"/files/{int(file_id)}/download_link.json"
    )
    req = urllib.request.Request(url, headers={
        "apikey": api_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Application-Name": "ModAgent",
        "Application-Version": "1.3.0",
    })
    try:
        with urllib.request.urlopen(
            req, context=ssl._create_unverified_context(), timeout=20,
        ) as response:
            status = int(getattr(response, "status", 200) or 200)
            content_type = response.headers.get("Content-Type", "")
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        diagnostics = {
            "path": "official_api",
            "http_status": int(exc.code),
            "content_type": exc.headers.get("Content-Type", ""),
            "response_kind": "json" if raw.lstrip().startswith(("{", "[")) else "text",
            "premium_or_site_flow_required": int(exc.code) in {401, 403},
        }
        try:
            data = json.loads(raw)
            message = (
                data.get("message") if isinstance(data, dict) else ""
            ) or ""
            if message:
                diagnostics["message"] = str(message)[:300]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        raise NexusDirectDownloadUnavailable(
            f"Nexus 官方下载接口返回 HTTP {exc.code}",
            diagnostics,
        ) from exc
    except Exception as exc:
        raise NexusDirectDownloadUnavailable(
            f"Nexus 官方下载接口请求失败：{type(exc).__name__}",
            {"path": "official_api", "transport_error": type(exc).__name__},
        ) from exc

    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NexusDirectDownloadUnavailable(
            "Nexus 官方下载接口没有返回 JSON",
            {
                "path": "official_api",
                "http_status": status,
                "content_type": content_type,
                "response_kind": "non_json",
            },
        ) from exc
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        cdn = row.get("URI") or row.get("uri") or row.get("url") or row.get("URL")
        if isinstance(cdn, str) and cdn.startswith(("http://", "https://")):
            return cdn
    raise NexusDirectDownloadUnavailable(
        "Nexus 官方下载接口未返回 CDN 地址",
        {
            "path": "official_api",
            "http_status": status,
            "content_type": content_type,
            "response_kind": type(data).__name__,
        },
    )


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


async def _cdp_trusted_click(
    ws, x: float, y: float, msg_id: int, timeout: float = 10
) -> bool:
    """Click rendered coordinates with trusted CDP mouse events.

    Nexus ignores synthetic ``element.click()`` in some download flows.  A
    browser-level mouse event follows the same path as a real user click while
    still leaving login, CAPTCHA and adult-content consent to the user.
    """
    commands = (
        ("mouseMoved", {}),
        ("mousePressed", {"button": "left", "clickCount": 1}),
        ("mouseReleased", {"button": "left", "clickCount": 1}),
    )
    for offset, (event_type, extra) in enumerate(commands):
        command_id = msg_id + offset
        await ws.send(json.dumps({
            "id": command_id,
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": event_type,
                "x": float(x),
                "y": float(y),
                **extra,
            },
        }))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if message.get("id") != command_id:
                continue
            if message.get("error"):
                return False
            break
    return True


async def _cdp_navigate(
    ws, url: str, msg_id: int, timeout: float = 10,
) -> bool:
    """Navigate the existing target so Nexus cannot strand us in a popup tab."""
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Page.navigate",
        "params": {"url": str(url)},
    }))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if message.get("id") != msg_id:
            continue
        return not bool(message.get("error"))


async def _cdp_command(
    ws, method: str, params: dict, msg_id: int, timeout: float = 10,
) -> dict:
    """Send a non-evaluate CDP command while ignoring unrelated page events."""
    await ws.send(json.dumps({
        "id": msg_id,
        "method": method,
        "params": params,
    }))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if message.get("id") != msg_id:
            continue
        return message


async def _nexus_automate_slow_download(
    ws, file_id: int, cdp_port: int = 0,
    stage_callback: Optional[Callable] = None,
) -> dict:
    """Drive Nexus' free-account UI and capture the generated CDN URL.

    Nexus changes CSS classes regularly, so selectors intentionally combine
    stable file-id attributes, href parameters, visible button text, and modal
    state instead of relying on one class name.
    """
    install_capture = r"""
    (() => {
      if (window.__modAgentDownloadCaptureInstalled) return true;
      window.__modAgentDownloadCaptureInstalled = true;
      window.__modAgentDownloadUrl = '';
      // Keep Nexus' free/premium choice in this disposable automation tab.
      // The current site may otherwise open a second target which this CDP
      // loop cannot observe.
      const originalWindowOpen = window.open.bind(window);
      window.open = function(url, target, features) {
        const href = String(url || '');
        if (/nexusmods\.com/i.test(href) && /(?:file_id=|download)/i.test(href)) {
          location.assign(href);
          return window;
        }
        return originalWindowOpen(url, target, features);
      };
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
          const requestUrl = typeof args[0] === 'string'
            ? args[0] : String(args[0]?.url || args[0] || '');
          if (requestUrl.includes('GenerateDownloadUrl')) {
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
        if (this.__modAgentUrl && this.__modAgentUrl.includes('GenerateDownloadUrl')) {
          this.addEventListener('load', () => capture(this.responseText), { once: true });
        }
        return originalSend.apply(this, args);
      };
      return true;
    })()
    """
    click_script = f"""
    (() => {{
      const fid = {int(file_id)};
      const visible = el => {{
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      }};
      const text = el => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
      const selector = 'a, button, [role="button"], input[type="button"], input[type="submit"]';
      const deepQuery = root => {{
        const found = [];
        const visit = node => {{
          if (!node?.querySelectorAll) return;
          for (const el of node.querySelectorAll('*')) {{
            if (el.matches?.(selector)) found.push(el);
            if (el.shadowRoot) visit(el.shadowRoot);
          }}
        }};
        visit(root);
        return found;
      }};
      const all = deepQuery(document).filter(visible);
      const component = [...document.querySelectorAll('mod-file-download')]
        .find(el => String(el.getAttribute('file-id') || '') === String(fid));
      const componentControls = component
        ? deepQuery(component).filter(visible)
        : [];
      const componentUrl = component?.getAttribute('download-url') || '';
      const componentLoggedIn = component?.getAttribute('user-is-logged-in') === 'true';
      if (/^https?:\\/\\//i.test(componentUrl)) {{
        return {{
          clicked: false, stage: 'component-url', direct_url: componentUrl,
          loggedIn: componentLoggedIn, url: location.href
        }};
      }}
      const prepare = (el, stage) => {{
        const style = getComputedStyle(el);
        if (el.disabled || el.getAttribute('aria-disabled') === 'true' ||
            style.pointerEvents === 'none') {{
          return {{clicked: false, stage: stage + '-disabled', text: text(el)}};
        }}
        // Keep navigation in this CDP target so the capture hook can be
        // reinstalled on the next document instead of losing a target=_blank tab.
        if (el.tagName === 'A') el.removeAttribute('target');
        el.scrollIntoView({{block: 'center', inline: 'center'}});
        const r = el.getBoundingClientRect();
        return {{
          clicked: false, ready_to_click: true, stage, text: text(el),
          x: r.left + r.width / 2, y: r.top + r.height / 2,
          href: el.href || ''
        }};
      }};
      const dialogs = all.filter(el =>
        !!el.closest?.('[role="dialog"], dialog, .modal, .reveal-modal, [class*="modal"]')
      );
      // Nexus may expose one Manual button on the page and a second Manual
      // download link in a dependency dialog. Finish the active dialog first.
      const actionable = dialogs.length ? dialogs : all;
      const slow = actionable.find(el => /slow\\s*download/i.test(text(el)));
      if (slow) return prepare(slow, 'slow');
      const exact = [...componentControls, ...actionable].find(el => {{
        const hay = [
          el.href, el.dataset?.id, el.dataset?.fileId, el.getAttribute('data-file-id'),
          el.getAttribute('data-id'), el.getAttribute('onclick')
        ].filter(Boolean).join(' ');
        return /^(manual|manual\\s+download)$/i.test(text(el)) &&
               (componentControls.includes(el) || hay.includes(String(fid)));
      }});
      const genericManual = actionable.filter(el =>
        /^(manual|manual\\s+download)$/i.test(text(el))
      );
      const manual = exact || (
        genericManual.length === 1 ? genericManual[0] : null
      );
      if (manual) return prepare(manual, 'manual');
      if (!exact && genericManual.length > 1) {{
        return {{
          clicked: false,
          stage: 'target-file-control-ambiguous',
          targetFileId: fid,
          manualControlCount: genericManual.length,
          title: document.title,
          url: location.href
        }};
      }}
      const files = all.find(el => {{
        const href = String(el.href || '');
        return /^files(?:\\s+\\d+)?$/i.test(text(el)) &&
               /[?&]tab=files(?:&|$)/i.test(href);
      }});
      if (files) return prepare(files, 'files');
      const dialog = document.querySelector('[role="dialog"], .modal, .reveal-modal, [class*="modal"]');
      if (dialog) {{
        const intermediate = [...dialog.querySelectorAll('a, button, [role="button"]')]
          .filter(visible)
          .find(el => /^(continue|download|download anyway|next)$/i.test(text(el)));
        if (intermediate) return prepare(intermediate, 'intermediate');
      }}
      const body = (document.body?.innerText || '').toLowerCase();
      const visibleSiteError = /something went wrong|download link for the file could not be retrieved/.test(body)
        ? 'download-link-not-retrieved' : '';
      const loginForm = !!document.querySelector(
        'form[action*="login" i] input[type="password"], input[name="password"], input[autocomplete="current-password"]'
      );
      const loggedIn = all.some(el =>
        /(?:sign\\s*out|log\\s*out|my\\s+profile|download\\s+history)/i.test(text(el))
      ) || componentLoggedIn;
      const slowAvailable = all.some(el => /slow\\s*download/i.test(text(el)));
      const manualAvailable = all.some(el => /^(manual|manual\\s+download)$/i.test(text(el)));
      return {{
        clicked: false,
        stage: slowAvailable || manualAvailable ? 'download-control-visible' : 'blocked',
        loggedIn,
        login: !loggedIn && (loginForm || /\\/login(?:[/?#]|$)/i.test(location.pathname)),
        siteDownloadError: componentUrl.startsWith('#ERROR-')
          ? componentUrl.slice(1, 160) : visibleSiteError,
        adult: /adult content|confirm.*age|content blocking/.test(body),
        captcha: /captcha|verify you are human|cloudflare/.test(body),
        slowAvailable,
        manualAvailable,
        title: document.title,
        url: location.href
      }};
    }})()
    """

    last_state = None
    clicked_actions: set[str] = set()
    unchanged_state_count = 0
    previous_fingerprint = ""
    capture_dir = os.path.join(
        DOWNLOADS_DIR, "_browser_capture", str(int(file_id))
    )
    os.makedirs(capture_dir, exist_ok=True)
    capture_started = time.time()
    last_reported_phase = ""

    def report_phase(phase: str, detail: str = "") -> None:
        nonlocal last_reported_phase
        if not stage_callback:
            return
        if phase == last_reported_phase and not detail:
            return
        last_reported_phase = phase
        try:
            stage_callback(phase, detail)
        except Exception:
            pass

    report_phase("browser_opened", "Nexus 文件页已打开")
    for old_path in glob.glob(os.path.join(capture_dir, "*")):
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass
    try:
        await _cdp_command(
            ws,
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": capture_dir,
                "eventsEnabled": True,
            },
            2099,
        )
    except Exception:
        pass
    for attempt in range(90):
        completed_downloads = [
            path for path in glob.glob(os.path.join(capture_dir, "*"))
            if os.path.isfile(path)
            and not path.lower().endswith((".crdownload", ".tmp"))
            and os.path.getsize(path) > 0
            and os.path.getmtime(path) >= capture_started - 1
        ]
        if completed_downloads:
            newest = max(completed_downloads, key=os.path.getmtime)
            report_phase(
                "browser_download_complete",
                f"浏览器下载完成：{os.path.basename(newest)}",
            )
            return {
                "url": Path(newest).resolve().as_uri(),
                "local_path": os.path.abspath(newest),
                "stage": "browser-download",
            }
        # Manual Download commonly performs a full navigation to Nexus'
        # free/premium choice page. A navigation destroys all page-level
        # monkey-patches, so reinstall the capture hook before every attempt
        # and, crucially, before clicking Slow download on the new document.
        await _cdp_eval(ws, install_capture, 2100 + attempt * 4)

        captured = await _cdp_eval(
            ws,
            "window.__modAgentDownloadUrl || ''",
            2101 + attempt * 4,
        )
        if isinstance(captured, str) and captured.startswith(("http://", "https://")):
            return {"url": captured, "stage": "captured"}

        state = await _cdp_eval(ws, click_script, 2102 + attempt * 4)
        if isinstance(state, dict):
            last_state = state
            direct_url = state.get("direct_url", "")
            if isinstance(direct_url, str) and direct_url.startswith(("http://", "https://")):
                return {"url": direct_url, "stage": "component-url"}
            stage = state.get("stage")
            if stage == "target-file-control-ambiguous":
                return {
                    "url": "",
                    "stage": stage,
                    "state": state,
                }
            partial_downloads = [
                path for path in glob.glob(os.path.join(capture_dir, "*"))
                if os.path.isfile(path)
                and path.lower().endswith((".crdownload", ".tmp"))
            ]
            if partial_downloads:
                report_phase("browser_downloading", "浏览器正在接收文件")
            elif state.get("captcha"):
                report_phase(
                    "waiting_verification",
                    "请在已打开的 Nexus 页面完成人机验证；完成后会自动继续",
                )
            elif last_reported_phase == "waiting_verification":
                report_phase(
                    "verification_resolved",
                    "已检测到验证完成，正在继续下载",
                )
            elif stage in {"manual", "slow", "intermediate", "files"}:
                report_phase("browser_preparing", "正在操作 Nexus 下载页面")
            action_key = "|".join([
                str(state.get("url") or ""),
                str(stage or ""),
                str(state.get("href") or ""),
                str(state.get("text") or ""),
            ])
            fingerprint = json.dumps({
                "url": state.get("url"),
                "stage": stage,
                "href": state.get("href"),
                "text": state.get("text"),
                "captcha": bool(state.get("captcha")),
                "login": bool(state.get("login")),
                "siteDownloadError": state.get("siteDownloadError"),
            }, ensure_ascii=False, sort_keys=True)
            if fingerprint == previous_fingerprint:
                unchanged_state_count += 1
            else:
                previous_fingerprint = fingerprint
                unchanged_state_count = 0
            if state.get("siteDownloadError") and any(
                "|slow|" in key for key in clicked_actions
            ):
                return {
                    "url": "",
                    "stage": "site-download-error",
                    "state": state,
                }
            should_click = (
                state.get("ready_to_click")
                and stage in {"manual", "slow", "intermediate", "files"}
                and action_key not in clicked_actions
            )
            if should_click:
                if stage == "files" and state.get("href"):
                    clicked = await _cdp_navigate(
                        ws, state["href"], 9000 + attempt * 3,
                    )
                else:
                    clicked = await _cdp_trusted_click(
                        ws, state.get("x", 0), state.get("y", 0),
                        9000 + attempt * 3,
                    )
                # Some Nexus controls are visible and valid but reject raw CDP
                # coordinates.  Use Playwright's auto-waiting click as a
                # downloader-internal fallback instead of asking the user to
                # click the exact same button by hand.
                if not clicked and cdp_port:
                    try:
                        from . import playwright_driver
                        fallback = await asyncio.to_thread(
                            playwright_driver.click_download_control,
                            cdp_port,
                            str(state.get("url") or ""),
                            str(stage or ""),
                            capture_dir,
                            int(file_id),
                        )
                    except Exception as exc:
                        fallback = {
                            "status": "failed", "clicked": False,
                            "error": type(exc).__name__,
                        }
                    clicked = bool(fallback.get("clicked"))
                    state["playwright_fallback"] = fallback.get("status", "")
                    fallback_downloads = fallback.get("downloads") or []
                    if fallback_downloads:
                        newest = max(fallback_downloads, key=os.path.getmtime)
                        report_phase(
                            "browser_download_complete",
                            f"浏览器下载完成：{os.path.basename(newest)}",
                        )
                        return {
                            "url": Path(newest).resolve().as_uri(),
                            "local_path": os.path.abspath(newest),
                            "stage": "browser-download",
                        }
                state["clicked"] = clicked
                if clicked:
                    clicked_actions.add(action_key)
                    unchanged_state_count = 0
                    if stage == "slow":
                        report_phase(
                            "browser_downloading",
                            "已触发 Nexus 免费下载，正在等待浏览器接收文件",
                        )
            if not should_click and (
                (state.get("login") and unchanged_state_count >= 4)
                or unchanged_state_count >= 8
            ):
                # A visible CAPTCHA is a recoverable wait state. Keep polling
                # so a user who solves it early resumes in this same download
                # instead of producing a failed batch followed by a retry.
                if state.get("captcha"):
                    await asyncio.sleep(0.75)
                    continue
                return {
                    "url": "",
                    "stage": "human-verification" if state.get("captcha") else "no-progress",
                    "state": state,
                }

        # Some Nexus layouts expose the final link directly in the modal.
        direct = await _cdp_eval(
            ws,
            r"""(() => {
              const links = [...document.querySelectorAll('a[href]')];
              const found = links.map(a => a.href).find(h =>
                /^https?:/i.test(h) &&
                (/nexus-cdn/i.test(h) || /premium\.nexusmods/i.test(h) ||
                 /cf-files\.nexusmods/i.test(h)));
              return found || '';
            })()""",
            2103 + attempt * 4,
        )
        if isinstance(direct, str) and direct.startswith(("http://", "https://")):
            return {"url": direct, "stage": "direct-link"}

        if any("|slow|" in key for key in clicked_actions):
            await asyncio.sleep(0.25)
        elif any("|manual|" in key for key in clicked_actions):
            await asyncio.sleep(0.5)
        else:
            await asyncio.sleep(0.75)

    return {
        "url": "",
        "stage": (
            "human-verification"
            if isinstance(last_state, dict) and last_state.get("captcha")
            else "timeout"
        ),
        "state": last_state,
    }


async def _find_captured_nexus_download(
    cdp_port: int, game_slug: str, mod_id: int
) -> str:
    """Recover a CDN URL captured after the LLM interacted with the kept page."""
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
    cdp_port: int, game_slug: str, mod_id: int, file_id: int, game_id: int,
    stage_callback: Optional[Callable] = None,
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

    page_url = _nexus_files_page_url(game_slug, mod_id, file_id)
    captured = await _find_captured_nexus_download(cdp_port, game_slug, mod_id)
    if captured:
        _NEXUS_MANUAL_GATES.pop(game_slug, None)
        return captured

    gate = _NEXUS_MANUAL_GATES.get(game_slug)
    reuse_tab = None
    if gate and time.monotonic() < gate["until"]:
        same_file = (
            int(gate.get("mod_id") or 0) == int(mod_id)
            and int(gate.get("file_id") or 0) == int(file_id)
        )
        if same_file:
            try:
                tabs = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{int(cdp_port)}/json/list", timeout=5
                ).read())
                reuse_tab = next(
                    (item for item in tabs if item.get("id") == gate.get("tab_id")),
                    None,
                )
            except Exception:
                reuse_tab = None
            _NEXUS_MANUAL_GATES.pop(game_slug, None)
        # A page waiting for verification belongs to this file only. Keep it
        # open, but let independent files continue in their own target.
    if gate and time.monotonic() >= gate["until"]:
        _NEXUS_MANUAL_GATES.pop(game_slug, None)

    tab = reuse_tab or _open_tab(cdp_port, page_url)
    created_tab = reuse_tab is None
    keep_tab = False
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
                "  const txt = await resp.text();"
                "  if (!resp.ok) return JSON.stringify({"
                "    error: resp.status,"
                "    content_type: resp.headers.get('content-type') || '',"
                "    cloudflare_challenge: /just a moment|cf-chl|cloudflare/i.test(txt),"
                "    body_kind: txt.trim().startsWith('<') ? 'html' : 'text'"
                "  });"
                "  try { JSON.parse(txt); } catch(_) {"
                "    return JSON.stringify({"
                "      bad_body: true, at: location.href,"
                "      content_type: resp.headers.get('content-type') || '',"
                "      body_kind: txt.trim().startsWith('<') ? 'html' : 'text'"
                "    });"
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
                                    f"类型={parsed.get('body_kind', 'unknown')},"
                                    f"content-type={parsed.get('content_type', '')}")
                        await asyncio.sleep(3)
                        continue
                    if "error" in parsed:
                        suffix = (
                            "（Cloudflare 验证页）"
                            if parsed.get("cloudflare_challenge") else ""
                        )
                        last_err = (
                            f"GenerateDownloadUrl 返回 HTTP {parsed['error']}{suffix};"
                            f"content-type={parsed.get('content_type', '')}"
                        )
                        break
                    cdn = parsed.get("url") or parsed.get("URL")
                    if cdn:
                        _NEXUS_MANUAL_GATES.pop(game_slug, None)
                        return cdn

                last_err = (
                    f"未获取到下载链接(原始返回: {value!r})。"
                    "当前页面接口没有生成直链，已转入可见页面按钮流程。"
                )
                await asyncio.sleep(3)

            automated = await _nexus_automate_slow_download(
                ws, file_id, cdp_port=cdp_port,
                stage_callback=stage_callback,
            )
            automated_url = automated.get("url", "")
            if automated_url:
                _NEXUS_MANUAL_GATES.pop(game_slug, None)
                return automated_url

            state = automated.get("state") or {}
            browser_diagnostics = {
                "path": "website",
                "generate_download_url": last_err or "",
                "automation_stage": automated.get("stage", ""),
                "site_download_error": state.get("siteDownloadError", ""),
                "logged_in": bool(state.get("loggedIn")),
                "login_required": bool(state.get("login")),
                "adult_confirmation_required": bool(state.get("adult")),
                "captcha": bool(state.get("captcha")),
                "target_file_id": int(file_id),
                "manual_control_count": int(
                    state.get("manualControlCount") or 0
                ),
            }
            human_gate = bool(
                state.get("login") or state.get("adult")
                or state.get("captcha")
            )
            if human_gate:
                keep_tab = True
                _NEXUS_MANUAL_GATES[game_slug] = {
                    "until": time.monotonic() + _NEXUS_MANUAL_GATE_SECONDS,
                    "page_url": state.get("url") or page_url,
                    "tab_id": tab.get("id", ""),
                    "mod_id": int(mod_id),
                    "file_id": int(file_id),
                }
            else:
                _NEXUS_MANUAL_GATES.pop(game_slug, None)
                _close_tab(cdp_port, tab.get("id", ""))
                created_tab = False
            reason = _nexus_gate_reason(state, automated.get("stage", ""))
            raise NexusManualDownloadRequired(
                state.get("url") or page_url,
                reason,
                diagnostics=browser_diagnostics,
            )
    finally:
        if not keep_tab and created_tab:
            _close_tab(cdp_port, tab.get("id", ""))


# ── Step 3: 下载文件 ──

def download_file(url: str, local_path: str, progress_callback: Optional[Callable] = None):
    """下载 CDN 直链，支持断点续传 + 完整性校验。
    限速/断流导致中途中断时，用 HTTP Range 从断点续传，下完核对总大小，不完整不入库。"""
    _raise_if_download_cancelled()
    if not url or url == 'None':
        raise DownloadFailure(
            "下载链接为空或无效，已停止自动重试。",
            failure_kind="invalid_url",
            retryable=False,
            attempts=0,
        )

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    ctx = ssl._create_unverified_context()
    tmp_path = local_path + ".part"

    downloaded = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    total = None
    stall = 0  # 连续无进展/临时网络失败次数

    for attempt in range(12):
        _raise_if_download_cancelled()
        headers = {"User-Agent": USER_AGENT}
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=120)
        except Exception as e:
            _raise_if_download_cancelled()
            kind, retryable, http_status = _classify_download_error(e)
            attempt_count = stall + 1
            if not retryable:
                raise DownloadFailure(
                    _download_failure_message(kind, attempt_count, http_status),
                    failure_kind=kind,
                    retryable=False,
                    attempts=attempt_count,
                    http_status=http_status,
                ) from e
            stall = attempt_count
            if stall >= 5:
                raise DownloadFailure(
                    _download_failure_message(kind, stall, http_status),
                    failure_kind=kind,
                    retryable=True,
                    attempts=stall,
                    http_status=http_status,
                ) from e
            for _ in range(20):
                _raise_if_download_cancelled()
                time.sleep(.1)
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
                _raise_if_download_cancelled()
                try:
                    chunk = resp.read(65536)
                except Exception:
                    _raise_if_download_cancelled()
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
                raise DownloadFailure(
                    f"下载连续 5 次没有进展，文件仍不完整：{downloaded}/{total} 字节。",
                    failure_kind="download_stalled",
                    retryable=True,
                    attempts=stall,
                )
            for _ in range(20):
                _raise_if_download_cancelled()
                time.sleep(.1)
        else:
            stall = 0
    else:
        raise DownloadFailure(
            f"下载尝试次数已用尽，文件仍不完整：{downloaded}/{total} 字节。",
            failure_kind="retry_exhausted",
            retryable=True,
            attempts=12,
        )

    size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    if size == 0:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise DownloadFailure(
            "下载结果为空文件，已停止处理；请重新核验下载来源。",
            failure_kind="empty_download",
            retryable=False,
            attempts=1,
        )
    if total and size < total:
        raise DownloadFailure(
            f"下载文件不完整：{size}/{total} 字节；稍后可手动重试。",
            failure_kind="incomplete_download",
            retryable=True,
            attempts=1,
        )

    _raise_if_download_cancelled()
    os.replace(tmp_path, local_path)
    return local_path


def import_local_download(
    source_path: str,
    local_path: str,
    progress_callback: Optional[Callable] = None,
) -> str:
    """Move a browser-completed file into managed cache without downloading it again."""
    _raise_if_download_cancelled()
    source_path = os.path.abspath(source_path)
    local_path = os.path.abspath(local_path)
    if source_path == local_path:
        if progress_callback:
            progress_callback(1.0)
        return local_path
    if not os.path.isfile(source_path):
        raise DownloadFailure(
            "浏览器报告下载完成，但临时文件已经不存在。",
            failure_kind="browser_file_missing",
            retryable=True,
            attempts=1,
        )
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp_path = local_path + ".part"
    for stale in (tmp_path,):
        try:
            if os.path.exists(stale):
                os.remove(stale)
        except OSError:
            pass
    try:
        # Browser capture and managed cache normally share one volume, making
        # this an atomic metadata move instead of a second 100 MB byte stream.
        os.replace(source_path, tmp_path)
        if progress_callback:
            progress_callback(1.0)
    except OSError:
        total = max(1, os.path.getsize(source_path))
        copied = 0
        with open(source_path, "rb") as src, open(tmp_path, "wb") as dst:
            while True:
                _raise_if_download_cancelled()
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress_callback(min(copied / total, 1.0))
        os.remove(source_path)
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
    stage_callback: Optional[Callable] = None,
    file_id: Optional[int] = None,
) -> dict:
    """完整下载一个 mod 的标准流程（按 SOP）。传入 file_id 可直接下载指定变体。"""
    _raise_if_download_cancelled()
    # 0. 检查本地缓存 — 命中直接返回，不要求开 Chrome
    cached = find_cached_nexus_download(game_slug, mod_id, file_id)
    if cached:
        if stage_callback:
            stage_callback("cache_hit", "已命中 ModAgent 下载缓存")
        return {"mod_id": mod_id, "file_id": file_id,
                "local_path": cached, "cached": True,
                "download_stage": "cache_hit"}

    # 1. 前置检查 — 真要下载才需要 Chrome
    ws_url = preflight_check(cdp_port, api_key)
    _raise_if_download_cancelled()
    if stage_callback:
        stage_callback("preparing", "正在确认 Nexus 文件与下载页面")

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
    # file_id 是 Nexus 文件资产的稳定身份。放进文件名可避免同一 Mod 的
    # 多个变体互相覆盖，也让后续安装能够证明使用了用户选中的文件。
    filename = f"{mod_id}_f{file_id}_{safe_name}_v{version}.zip"
    local_path = os.path.join(DOWNLOADS_DIR, game_slug, filename)

    last_err = None
    max_attempts = 2
    for attempt in range(max_attempts):
        _raise_if_download_cancelled()
        # 每次都重新生成直链（旧链可能已过期）。先走官方 API；
        # 免费账号被拒时再回落到同一文件页里的 Slow download 流程。
        cdn_url = ""
        direct_failure = None
        try:
            cdn_url = get_download_url_api(
                game_slug, mod_id, file_id, api_key,
            )
        except NexusDirectDownloadUnavailable as exc:
            direct_failure = exc

        try:
            if not cdn_url:
                _raise_if_download_cancelled()
                cdn_url = await get_download_url_filepage(
                    cdp_port, game_slug, mod_id, file_id, game_id,
                    stage_callback=stage_callback,
                )
        except NexusManualDownloadRequired as exc:
            if direct_failure:
                exc.diagnostics["direct_api"] = direct_failure.diagnostics
            raise
        except RuntimeError as e:
            last_err = e
            # get_download_url_filepage 已在同一个标签内重试三次。继续外层循环
            # 只会反复开 Files 页，并不能修复登录、参数或站方确认问题。
            raise RuntimeError(
                f"下载 mod {mod_id} 失败: {e}"
            ) from e
        if not cdn_url or cdn_url == 'None':
            last_err = RuntimeError("获取下载链接失败")
            if attempt + 1 < max_attempts:
                _raise_if_download_cancelled()
                await asyncio.sleep(.5)
            continue

        try:
            _raise_if_download_cancelled()
            parsed_url = urllib.parse.urlparse(cdn_url)
            if parsed_url.scheme.lower() == "file":
                browser_path = urllib.request.url2pathname(parsed_url.path)
                if parsed_url.netloc:
                    browser_path = f"//{parsed_url.netloc}{browser_path}"
                if stage_callback:
                    stage_callback(
                        "importing",
                        "浏览器下载已完成，正在导入 ModAgent 缓存",
                    )
                import_local_download(
                    browser_path, local_path, progress_callback
                )
                transfer_stage = "browser_download"
            else:
                if stage_callback:
                    stage_callback("transferring", "正在接收下载文件")
                download_file(cdn_url, local_path, progress_callback)  # 内部断点续传 + 字节完整性校验
                transfer_stage = "direct_download"
            _raise_if_download_cancelled()
        except Exception as e:
            if isinstance(e, task_control.TaskCancelled):
                raise
            last_err = e  # 链接中途失效/断流 → 保留 .part，下次用新链续传
            kind, retryable, status = _classify_download_error(e)
            if not retryable:
                raise DownloadFailure(
                    f"下载 mod {mod_id} 失败: {e}",
                    failure_kind=kind,
                    retryable=False,
                    attempts=attempt + 1,
                    http_status=status,
                ) from e
            if attempt + 1 < max_attempts:
                _raise_if_download_cancelled()
                await asyncio.sleep(.5)
            continue

        # 字节完整 → 再验解压完整性（抓"满大小但内部损坏"）
        if stage_callback:
            stage_callback("verifying", "正在校验压缩包完整性")
        if _verify_archive(local_path):
            _remember_download(local_path, game_slug, mod_id, file_id)
            if stage_callback:
                stage_callback("download_complete", "文件已下载并校验通过")
            return {
                "mod_id": mod_id, "file_id": file_id, "local_path": local_path,
                "cached": False, "mod_name": mod_name, "version": version,
                "download_stage": transfer_stage,
            }
        # 损坏 → 删掉（含 .part）重新整下
        last_err = RuntimeError("压缩包完整性校验失败")
        for p in (local_path, local_path + ".part"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        if attempt + 1 < max_attempts:
            _raise_if_download_cancelled()
            await asyncio.sleep(.5)

    kind, retryable, status = _classify_download_error(
        last_err or RuntimeError("下载结果未通过完整性校验")
    )
    raise DownloadFailure(
        f"下载 mod {mod_id} 失败（自动尝试 {max_attempts} 次）: {last_err}",
        failure_kind=kind if kind != "unknown" else "retry_exhausted",
        retryable=retryable,
        attempts=max_attempts,
        http_status=status,
    )


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
        query_literal = json.dumps(str(query or ""))
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
            setter.call(input, {query_literal});
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
                    try:
                        rows = json.loads(value)
                        return _filter_cdp_search_results(query, rows)
                    except: pass
                if isinstance(value, list):
                    return _filter_cdp_search_results(query, value)
                return []


def _filter_cdp_search_results(query: str, rows: list[dict]) -> list[dict]:
    """Reject Nexus' default browse list when the search form ignored a query."""
    broad = {
        "latest", "popular", "trending", "new", "hot", "best", "recommended",
        "mods", "mod", "最近", "最新", "热门", "推荐",
    }
    cleaned = str(query or "").casefold()
    for word in broad:
        cleaned = cleaned.replace(word, " ")
    wanted = {
        token for token in re.findall(r"[a-z0-9\u3400-\u9fff]+", cleaned)
        if len(token) >= 2
    }
    if not wanted:
        return rows[:10]
    filtered = []
    for row in rows or []:
        name = re.sub(
            r"[^a-z0-9\u3400-\u9fff]+", "",
            str(row.get("name") or "").casefold(),
        )
        if any(token in name for token in wanted):
            filtered.append(row)
    return filtered[:10]
