"""GitHub Releases 适配器：解析仓库最新 release 的资产并下载;Search API 搜仓库。
很多工具型 mod（脚本扩展、BepInEx 插件、框架）只发在 GitHub。"""
import re
import platform
import urllib.error
import urllib.parse

from . import _http_json, _safe, _dest
from .. import downloader


_MOD_EVIDENCE = {
    "mod", "mods", "modding", "plugin", "plugins", "bepinex", "ue4ss",
    "melonloader", "reshade", "nexusmods", "thunderstore", "gamebanana",
    "workshop",
}
_GENERIC_NON_MOD_NAMES = {
    "config", ".config", "utils", "utility", "log", "logs", "faults",
    "template", "tutorial", "example", "examples",
}
_FRAMEWORK_ALIASES = {
    "bepinex": ("bepinex/bepinex", "bepinex"),
    "ue4ss": ("ue4ss-re/ue4ss", "ue4ss"),
    "melonloader": ("lavagang/melonloader", "melonloader"),
    "fluffymodmanager": ("fluffy-mods/modmanager", "modmanager"),
}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _game_aliases(game_name: str) -> set[str]:
    raw = str(game_name or "").strip()
    aliases = {_compact(raw)}
    # Strip storefront trademark suffixes without splitting the game title
    # into broad single words.
    aliases.add(_compact(re.sub(r"[™®©]", "", raw)))
    return {item for item in aliases if len(item) >= 4}


def _evidence(item: dict, game_name: str) -> tuple[list[str], list[str]]:
    text = " ".join([
        str(item.get("name") or ""),
        str(item.get("full_name") or ""),
        str(item.get("summary") or ""),
        " ".join(item.get("topics") or []),
        str(item.get("homepage") or ""),
    ])
    compact_text = _compact(text)
    game_hits = [
        alias for alias in _game_aliases(game_name)
        if alias in compact_text
    ]
    tokens = _tokens(text)
    mod_hits = sorted(tokens & _MOD_EVIDENCE)
    return game_hits, mod_hits


def _is_explicit_framework(query: str, item: dict) -> bool:
    compact_query = _compact(query)
    full_name = str(item.get("full_name") or "").casefold()
    name = _compact(str(item.get("name") or ""))
    for alias, (official, token) in _FRAMEWORK_ALIASES.items():
        if alias in compact_query and (
            full_name == official or token in name
        ):
            return True
    return False


def _filter_game_mod_results(
    rows: list[dict], query: str, game_name: str,
) -> list[dict]:
    """Require both game identity and Mod/install evidence.

    GitHub has no game-Mod category.  Search hits caused only by logs, config
    files or generic utility words must not enter the recommendation table.
    Official loader/framework repositories are the one deliberate exception
    when the user explicitly searched for that framework.
    """
    kept = []
    for item in rows:
        game_hits, mod_hits = _evidence(item, game_name)
        generic_name = _compact(str(item.get("name") or "")) in {
            _compact(value) for value in _GENERIC_NON_MOD_NAMES
        }
        framework = _is_explicit_framework(query, item)
        if not framework and (not game_hits or not mod_hits or generic_name):
            continue
        enriched = dict(item)
        enriched["game_evidence"] = game_hits
        enriched["mod_evidence"] = mod_hits or (
            ["official_framework_repository"] if framework else []
        )
        enriched["relevance_verified"] = True
        kept.append(enriched)
    return kept


def _search_once(query: str, limit: int) -> list:
    """Run one GitHub repository search and normalize its results."""
    url = ("https://api.github.com/search/repositories?q=" + urllib.parse.quote(query)
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
            "topics": r.get("topics") or [],
            "homepage": r.get("homepage") or "",
            "stars": r.get("stargazers_count", 0),
            "updated_at": (r.get("pushed_at") or "")[:10],
            "archived": r.get("archived", False),
        })
    return out


def search(query: str, game_name: str = "", limit: int = 10) -> list:
    """GitHub Search API 搜仓库(公开,无需 key;未登录限流约 10 次/分)。
    把游戏名并入查询提高相关性;结果仍可能混入非 mod 仓库(教程/存档工具),
    由调用方读 summary/stars 判断——这是 GitHub 没有'游戏→mod'分类的固有限制。"""
    base_query = (query or "").strip()
    game_name = (game_name or "").strip()
    if not base_query:
        raise RuntimeError("搜索词为空")
    # Constrain repository search to repository metadata.  Code/log hits are
    # too noisy to be treated as Mod candidates.
    scoped_query = " ".join(
        x for x in (f'"{game_name}"' if game_name else "", base_query,
                    "in:name,description,topics")
        if x
    )
    out = _filter_game_mod_results(
        _search_once(scoped_query, max(limit * 3, 10)),
        base_query,
        game_name,
    )[:limit]
    if out or not game_name:
        for item in out:
            item["search_scope"] = "game"
        return out

    # Only an explicitly named loader/framework may use global fallback.
    # Broad feature searches returning no game-scoped evidence stay empty.
    if not any(alias in _compact(base_query) for alias in _FRAMEWORK_ALIASES):
        return []
    out = [
        item for item in _search_once(
            f"{base_query} in:name,description,topics", max(limit * 2, 10)
        )
        if _is_explicit_framework(base_query, item)
    ][:limit]
    for item in out:
        item["search_scope"] = "global_fallback"
        item["game_evidence"] = []
        item["mod_evidence"] = ["official_framework_repository"]
        item["relevance_verified"] = True
    return out


def _parse_repo(url: str):
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url)
    if not m:
        return None
    return m.group(1), m.group(2).replace(".git", "")


def pick_release_asset(
    assets: list,
    platform_name: str | None = None,
    architecture: str | None = None,
):
    """Pick a production archive compatible with the current platform."""
    platform_name = (platform_name or platform.system()).casefold()
    architecture = (architecture or platform.machine()).casefold()
    wants_windows = platform_name.startswith("win")
    wants_x64 = architecture in {"amd64", "x86_64", "x64"}

    archives = [
        asset for asset in (assets or [])
        if str(asset.get("name") or "").casefold().endswith(
            (".zip", ".7z", ".rar")
        )
    ]
    if not archives:
        return None

    def name_of(asset):
        return str(asset.get("name") or "").casefold()

    production = [
        asset for asset in archives
        if not any(token in name_of(asset) for token in (
            "zdev", "-dev", "_dev", "debug", "symbols", ".pdb",
            "source", "src.zip",
        ))
    ] or archives

    if wants_windows:
        production = [
            asset for asset in production
            if not any(token in name_of(asset) for token in (
                "linux", "macos", "osx", "darwin", "android",
            ))
        ]
    if not production:
        return None

    def score(asset):
        name = name_of(asset)
        value = 0
        if wants_windows:
            if re.search(r"(?:win|windows)[-_ ]?(?:x64|64bit|amd64)", name):
                value += 700
            elif "win64" in name:
                value += 700
            elif "windows" in name or re.search(
                r"(?:^|[_-])win(?:[_-]|$)", name
            ):
                value += 450
            if wants_x64 and re.search(
                r"(?:^|[_-])(?:x64|amd64)(?:[_-]|$)", name
            ):
                value += 180
            if wants_x64 and re.search(
                r"(?:^|[_-])x86(?:[_-]|$)", name
            ):
                value -= 220
        if "patcher" in name:
            value -= 300
        if any(token in name for token in ("runtime", "standalone", "full")):
            value += 40
        return value

    # Preserve the author's release ordering for equal-quality candidates.
    return max(
        enumerate(production),
        key=lambda pair: (score(pair[1]), -pair[0]),
    )[1]


_pick_asset = pick_release_asset


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
