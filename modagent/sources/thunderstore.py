"""Thunderstore 适配器：Unity/BepInEx 游戏（雨中冒险2、Lethal Company、Valheim、REPO 等）。
包格式标准化、API 全公开、无需认证/登录/浏览器。"""
import re
import time

from . import _http_json, _safe, _dest
from .. import downloader

_COMMUNITIES = None              # 缓存社区列表
_PKG_CACHE = {}                  # community -> (ts, packages)
_PKG_TTL = 600                   # 包列表缓存 10 分钟


def list_communities() -> list:
    """获取 Thunderstore 全部社区(=游戏)，带分页。"""
    global _COMMUNITIES
    if _COMMUNITIES is not None:
        return _COMMUNITIES
    comms = []
    url = "https://thunderstore.io/api/experimental/community/"
    for _ in range(8):  # 最多翻 8 页
        data = _http_json(url)
        comms.extend(data.get("results", []) if isinstance(data, dict) else (data or []))
        nxt = data.get("pagination", {}).get("next_link") if isinstance(data, dict) else None
        if not nxt:
            break
        url = nxt
    _COMMUNITIES = comms
    return comms


def find_community(game_name: str):
    """把当前游戏名自动匹配到 Thunderstore 社区 slug（不写死游戏名）。"""
    name = (game_name or "").strip().lower()
    if not name:
        return None
    comms = list_communities()
    # 1) 精确名匹配
    for c in comms:
        if (c.get("name", "") or "").lower() == name:
            return c.get("identifier")
    # 2) 推导 kebab slug 直接匹配 identifier
    derived = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    for c in comms:
        if c.get("identifier") == derived:
            return c.get("identifier")
    # 3) 包含匹配（宽松）
    for c in comms:
        cn = (c.get("name", "") or "").lower()
        if cn and (name in cn or cn in name):
            return c.get("identifier")
    return None


def _packages(community: str, force_refresh: bool = False) -> list:
    now = time.time()
    cached = _PKG_CACHE.get(community)
    if not force_refresh and cached and now - cached[0] < _PKG_TTL:
        return cached[1]
    pkgs = _http_json(f"https://thunderstore.io/c/{community}/api/v1/package/")
    if not isinstance(pkgs, list):
        raise RuntimeError("Thunderstore package API returned an invalid response")
    _PKG_CACHE[community] = (now, pkgs)
    return pkgs


def list_packages(community: str, force_refresh: bool = False) -> list:
    """Return the complete community package ledger for identity matching."""
    return list(_packages(community, force_refresh=force_refresh))


def _parse(url: str):
    # 形如 /p/<ns>/<name>/ 或 /package/<ns>/<name>/
    m = re.search(r"(?:/p/|/package/)([^/\s]+)/([^/\s#?]+)", url)
    if m:
        return m.group(1), m.group(2)
    return None


def download(url: str, game_slug: str, progress_callback=None) -> dict:
    p = _parse(url)
    if not p:
        raise RuntimeError("无法解析 Thunderstore 链接（需形如 thunderstore.io/c/<游戏>/p/<作者>/<包>/）")
    ns, name = p
    data = _http_json(f"https://thunderstore.io/api/experimental/package/{ns}/{name}/")
    latest = data.get("latest", {}) or {}
    dlurl = latest.get("download_url")
    if not dlurl:
        raise RuntimeError("Thunderstore 包没有可下载版本")
    ver = latest.get("version_number", "")
    dest = _dest(game_slug, f"ts_{_safe(ns)}_{_safe(name)}_{_safe(ver)}.zip")
    downloader.download_file(dlurl, dest, progress_callback)
    return {"local_path": dest, "name": f"{ns}-{name}", "source": "thunderstore", "version": ver}


def search(community: str, query: str, limit: int = 12,
           force_refresh: bool = False) -> list:
    """在某社区(=游戏)的包列表里按名称/作者/简介搜，按下载量排序。"""
    pkgs = _packages(community, force_refresh=force_refresh)
    q = (query or "").strip().lower()
    out = []
    for p in pkgs:
        versions = p.get("versions") or [{}]
        desc = versions[0].get("description", "") if versions else ""
        hay = f"{p.get('name','')} {p.get('owner','')} {desc}".lower()
        if not q or q in hay:
            # v1 接口下载量在各版本里，累加得总量
            dl = p.get("total_downloads") or sum(v.get("downloads", 0) for v in versions)
            out.append({
                "name": p.get("name", ""),
                "full_name": p.get("full_name", ""),
                "url": p.get("package_url", ""),
                "summary": desc[:140],
                "downloads": dl,
                "pinned": p.get("is_pinned", False),
                "owner": p.get("owner", ""),
                "latest_version": str(versions[0].get("version_number", "")) if versions else "",
            })
    out.sort(key=lambda x: x["downloads"], reverse=True)
    return out[:limit]
