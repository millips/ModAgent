"""GitHub Releases 适配器：解析仓库最新 release 的资产并下载;Search API 搜仓库。
很多工具型 mod（脚本扩展、BepInEx 插件、框架）只发在 GitHub。"""
import re
import urllib.error
import urllib.parse

from . import _http_json, _safe, _dest
from .. import downloader


def search(query: str, game_name: str = "", limit: int = 10) -> list:
    """GitHub Search API 搜仓库(公开,无需 key;未登录限流约 10 次/分)。
    把游戏名并入查询提高相关性;结果仍可能混入非 mod 仓库(教程/存档工具),
    由调用方读 summary/stars 判断——这是 GitHub 没有'游戏→mod'分类的固有限制。"""
    q = " ".join(x for x in [(query or "").strip(), (game_name or "").strip()] if x)
    if not q:
        raise RuntimeError("搜索词为空")
    url = ("https://api.github.com/search/repositories?q=" + urllib.parse.quote(q)
           + f"&sort=stars&order=desc&per_page={max(1, min(limit, 30))}")
    try:
        data = _http_json(url)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError("GitHub 搜索 API 暂时限流(未登录约每分钟 10 次)。请等 1 分钟再试。")
        raise RuntimeError(f"GitHub 搜索失败: HTTP {e.code}")
    out = []
    for r in data.get("items", [])[:limit]:
        out.append({
            "name": r.get("name", ""),
            "full_name": r.get("full_name", ""),
            "url": r.get("html_url", ""),
            "summary": (r.get("description") or "")[:140],
            "stars": r.get("stargazers_count", 0),
            "updated_at": (r.get("pushed_at") or "")[:10],   # 最近推送,陈旧判断用
            "archived": r.get("archived", False),            # 已归档=作者弃更,如实标注
        })
    return out


def _parse_repo(url: str):
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url)
    if not m:
        return None
    return m.group(1), m.group(2).replace(".git", "")


def _pick_asset(assets: list):
    for a in assets:
        n = (a.get("name") or "").lower()
        if n.endswith((".zip", ".rar", ".7z")):
            return a
    return assets[0] if assets else None


def download(url: str, game_slug: str, progress_callback=None) -> dict:
    # 1) 直接资产链接
    if "/releases/download/" in url:
        fn = url.split("/")[-1]
        dest = _dest(game_slug, "gh_" + _safe(fn))
        downloader.download_file(url, dest, progress_callback)
        return {"local_path": dest, "name": fn, "source": "github", "version": ""}

    # 2) 仓库链接 → 取 latest release
    parsed = _parse_repo(url)
    if not parsed:
        raise RuntimeError("无法解析 GitHub 链接（需形如 github.com/owner/repo）")
    owner, repo = parsed
    try:
        rel = _http_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError("GitHub API 暂时限流（未登录每小时仅 60 次）。请稍后再试，或直接粘贴该 release 资产的下载直链（形如 .../releases/download/.../xxx.zip），可绕过 API。")
        if e.code == 404:
            raise RuntimeError(f"未找到 {owner}/{repo} 的 release（仓库可能没有发布版本）")
        raise RuntimeError(f"GitHub 获取 release 失败: HTTP {e.code}")
    asset = _pick_asset(rel.get("assets", []))
    if not asset:
        raise RuntimeError(f"{owner}/{repo} 的最新 release 没有可下载的资产文件")
    tag = rel.get("tag_name", "")
    fn = asset.get("name", "release")
    dest = _dest(game_slug, f"gh_{_safe(repo)}_{_safe(tag)}_{_safe(fn)}")
    downloader.download_file(asset["browser_download_url"], dest, progress_callback)
    return {"local_path": dest, "name": f"{repo} {tag}".strip(), "source": "github", "version": tag}
