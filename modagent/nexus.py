import json
import ssl
import time
import urllib.request
import urllib.parse
import urllib.error
import re
from typing import Optional

USER_AGENT = "ModAgent/0.1"

# Cache for updated mod IDs per game (max 20 entries to prevent unbounded growth)
_MOD_CACHE: dict[str, tuple[float, list[dict]]] = {}
_MOD_CACHE_MAX = 20
_GAME_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}
_GAME_DISCOVERY_TTL = 24 * 3600


class NexusSearchUnavailable(RuntimeError):
    """Nexus could not be queried; this is not an empty search result."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _normalise_game_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"[™®©]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def _game_name_tokens(name: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _normalise_game_name(name).lower())
        if token not in {"the", "game", "edition", "pc"} and len(token) > 1
    }


def _match_game_catalog(game_name: str, games) -> dict | None:
    """Match a display name against Nexus' official game catalogue."""
    wanted = _game_name_tokens(game_name)
    if not wanted:
        return None
    candidates = []
    for item in games if isinstance(games, list) else []:
        if not isinstance(item, dict):
            continue
        slug = str(
            item.get("domain_name") or item.get("domainName")
            or item.get("slug") or ""
        ).strip().lower()
        title = str(item.get("name") or "")
        if not slug:
            continue
        seen = _game_name_tokens(f"{title} {slug}")
        overlap = len(wanted & seen)
        # Require all meaningful words for short names, and nearly all for long
        # names. This avoids mapping similarly named sequels to each other.
        required = len(wanted) if len(wanted) <= 3 else len(wanted) - 1
        if overlap >= required:
            exact = int(_normalise_game_name(title).casefold()
                        == _normalise_game_name(game_name).casefold())
            candidates.append((exact, overlap, slug, title))
    if not candidates:
        return None
    _, _, slug, title = max(candidates)
    return {
        "status": "available",
        "slug": slug,
        "game_id": int(item.get("id") or 0),
        "evidence": f"Nexus API games catalogue: {title}",
        "reason": "verified in Nexus official game catalogue",
    }


def discover_game(game_name: str, tavily_key: str = "",
                  nexus_api_key: str = "") -> dict:
    """Resolve an unknown game name to a Nexus game slug.

    A missing static mapping is not evidence that Nexus has no page.  Discovery
    is deliberately conservative: it returns ``not_detected`` rather than
    claiming that a game is unavailable when search cannot prove it.
    """
    name = _normalise_game_name(game_name)
    # Credential availability is part of the cache key. Otherwise an early
    # credentials_missing result would hide a valid discovery for 24 hours
    # after the user configured their API keys.
    cache_key = (name.casefold(), bool(tavily_key), bool(nexus_api_key))
    now = time.time()
    cached = _GAME_DISCOVERY_CACHE.get(cache_key)
    if cached and now - cached[0] < _GAME_DISCOVERY_TTL:
        return dict(cached[1])

    result = {
        "status": "not_detected",
        "slug": "",
        "evidence": "",
        "reason": "no verified Nexus game page was discovered",
    }
    if not name:
        result["reason"] = "game name is empty"
    elif nexus_api_key:
        try:
            catalog = _api("https://api.nexusmods.com/v1/games.json",
                           nexus_api_key)
            games = catalog if isinstance(catalog, list) else catalog.get("data", [])
            matched = _match_game_catalog(name, games)
            if matched:
                result = matched
        except Exception as exc:
            result["status"] = "search_failed"
            result["reason"] = f"Nexus game catalogue failed: {exc}"[:160]

    if name and result.get("status") != "available" and tavily_key:
        # Tavily remains a fallback when the official catalogue is unavailable
        # or has not yet indexed a newly-created game page.
        result = {
            "status": "not_detected",
            "slug": "",
            "evidence": "",
            "reason": "no verified Nexus game page was discovered",
        }
        body = json.dumps({
            "query": f'site:nexusmods.com/games "{name}"',
            "search_depth": "basic",
            "include_domains": ["nexusmods.com"],
            "max_results": 8,
        }).encode()
        ctx = ssl._create_unverified_context()
        try:
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {tavily_key}",
                },
            )
            payload = json.loads(
                urllib.request.urlopen(req, context=ctx, timeout=12).read()
            )
            candidates = []
            wanted = _game_name_tokens(name)
            for item in payload.get("results", []):
                url = item.get("url", "")
                match = re.search(
                    r"nexusmods\.com/games/([a-z0-9-]+)(?:/|$)",
                    url,
                    re.IGNORECASE,
                )
                if match:
                    haystack = " ".join([
                        item.get("title", ""),
                        item.get("content", ""),
                        url.replace("-", " "),
                    ])
                    seen = _game_name_tokens(haystack)
                    overlap = len(wanted & seen)
                    required = 1 if len(wanted) <= 1 else min(2, len(wanted))
                    if overlap >= required:
                        candidates.append((overlap, match.group(1).lower(), url))
            if candidates:
                _, slug, url = max(candidates, key=lambda item: item[0])
                result = {
                    "status": "available",
                    "slug": slug,
                    "evidence": url,
                    "reason": "verified Nexus game page discovered",
                }
        except Exception as exc:
            result["status"] = "search_failed"
            result["reason"] = (str(exc) or type(exc).__name__)[:160]
    elif name and result.get("status") != "available" and not nexus_api_key:
        result["status"] = "credentials_missing"
        result["reason"] = (
            "Nexus or Tavily API key is required for unknown-game discovery"
        )

    _GAME_DISCOVERY_CACHE[cache_key] = (now, dict(result))
    return result


def _api(url: str, api_key: str) -> dict:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers={
        "apikey": api_key, "Accept": "application/json", "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return json.loads(resp.read())


def resolve_game_id(game_slug: str, api_key: str) -> int:
    """Resolve Nexus' numeric game id for a domain slug (including ``site``)."""
    if not (game_slug or "").strip() or not api_key:
        return 0
    try:
        data = _api(
            f"https://api.nexusmods.com/v1/games/{game_slug.strip()}.json",
            api_key,
        )
        return int(data.get("id") or data.get("game_id") or 0)
    except Exception:
        return 0


def search(query: str, game_slug: str, api_key: str, cdp_port: int = 18888, game_id: int = 0, tavily_key: str = "") -> list[dict]:
    """Search Nexus through independent routes without making CDP a choke point.

    Web search is best for discovery, the API cache is deterministic, and CDP
    is the last fallback because login challenges/page redesigns are the least
    reliable part of the chain.
    """
    if not (game_slug or "").strip():
        raise ValueError("game_mapping_missing: Nexus game slug is empty")

    # 1. Tavily web search
    if tavily_key:
        result = _search_via_tavily(query, game_slug, tavily_key)
        if result:
            return result

    api_error = None
    try:
        result = _search_api(query, game_slug, api_key, game_id)
        if result:
            return result
    except NexusSearchUnavailable as exc:
        api_error = exc

    # CDP is an adaptive final route, not a prerequisite for ordinary search.
    result = _search_cdp(query, game_slug, api_key, cdp_port, game_id)
    if result and not (len(result) == 1 and result[0].get("error")):
        return result
    if api_error:
        raise api_error
    return []


def _search_via_tavily(query: str, game_slug: str, api_key: str) -> list[dict]:
    """通过 Tavily 搜索 Nexus Mods，从 URL 提取 mod_id。"""
    import re, ssl

    if not api_key:
        return []

    search_query = f"site:nexusmods.com/{game_slug}/mods {query}"
    body = json.dumps({
        "query": search_query,
        "search_depth": "basic",
        "include_domains": ["nexusmods.com"],
        "max_results": 10,
    }).encode()

    ctx = ssl._create_unverified_context()
    try:
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read())
    except Exception:
        return []

    results = []
    for item in resp.get("results", []):
        url = item.get("url", "")
        m = re.search(rf"/{game_slug}/mods/(\d+)", url)
        if m:
            results.append({
                "mod_id": int(m.group(1)),
                "name": item.get("title", "").split(" at ")[0].strip()[:80],
                "summary": item.get("content", "")[:200],
                "endorsements": 0,
                "version": "",
                "updated": "",
            })
    return results


_TOOL_QUERY_WORDS = (
    "manager", "mod manager", "loader", "mod loader", "framework",
    "injector", "patcher", "tool", "utility", "ue4ss", "bepinex",
    "melonloader", "reframework",
    "管理器", "加载器", "框架", "注入器", "工具", "前置",
)


def is_tool_query(query: str) -> bool:
    """Return whether a query likely names a cross-game tool/framework."""
    text = (query or "").casefold()
    return any(word in text for word in _TOOL_QUERY_WORDS)


def search_tool_entries(query: str, tavily_key: str, api_key: str = "",
                        cdp_port: int = 18888, limit: int = 10) -> list[dict]:
    """Search Nexus globally for duplicate/canonical tool entries.

    Game pages often retain an old copy while the maintained tool moves to
    ``site/mods/<id>``. Each result therefore carries its own Nexus slug.
    """
    if not tavily_key or not (query or "").strip():
        return []
    body = json.dumps({
        "query": f'site:nexusmods.com "{query.strip()}" mod manager tool',
        "search_depth": "basic",
        "include_domains": ["nexusmods.com"],
        "max_results": max(1, min(limit, 20)),
    }).encode()
    ctx = ssl._create_unverified_context()
    try:
        req = urllib.request.Request(
            "https://api.tavily.com/search", data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tavily_key}",
            },
        )
        payload = json.loads(
            urllib.request.urlopen(req, context=ctx, timeout=10).read()
        )
    except Exception:
        return []

    found = []
    seen = set()
    for item in payload.get("results", []):
        url = item.get("url", "")
        match = re.search(
            r"nexusmods\.com/(?:games/)?([a-z0-9_-]+)/mods/(\d+)",
            url, re.IGNORECASE,
        )
        if not match:
            continue
        nexus_slug, mod_id = match.group(1).lower(), int(match.group(2))
        key = (nexus_slug, mod_id)
        if key in seen:
            continue
        seen.add(key)
        result = {
            "mod_id": mod_id,
            "nexus_slug": nexus_slug,
            "url": f"https://www.nexusmods.com/{nexus_slug}/mods/{mod_id}",
            "name": item.get("title", "").split(" at ")[0].strip()[:100],
            "summary": item.get("content", "")[:240],
            "source_scope": "nexus_global_tool_search",
        }
        if api_key:
            try:
                detail = get_detail(mod_id, nexus_slug, api_key, cdp_port)
                result.update({
                    "name": detail.get("name") or result["name"],
                    "summary": detail.get("summary") or result["summary"],
                    "version": detail.get("version", ""),
                    "updated_time": detail.get("updated_at", ""),
                    "author": detail.get("author", ""),
                    "endorsement_count": detail.get("endorsements", 0),
                    "downloads": detail.get("downloads", 0),
                    "file_id": detail.get("file_id"),
                    "staleness": detail.get("staleness"),
                })
            except Exception:
                pass
        found.append(result)
    return found


def rank_duplicate_entries(results: list[dict]) -> list[dict]:
    """Mark the newest same-name/same-author Nexus entry as canonical."""
    import datetime as _dt

    def normalized(value):
        return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())

    def timestamp(item):
        raw = item.get("updated_time") or item.get("updated") or ""
        try:
            return _dt.datetime.fromisoformat(
                str(raw).replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            return 0

    groups = {}
    for item in results:
        name = normalized(item.get("name"))
        if name:
            groups.setdefault(name, []).append(item)

    for group in groups.values():
        if len(group) < 2:
            continue
        known_authors = {
            normalized(item.get("author")) for item in group
            if normalized(item.get("author"))
        }
        # Exact title plus matching/unknown author is enough to compare mirrors.
        # If two explicitly different authors reused a generic title, leave them
        # separate rather than declaring one superseded.
        if len(known_authors) > 1:
            continue
        winner = max(group, key=lambda item: (
            timestamp(item),
            item.get("nexus_slug") == "site",
            str(item.get("version") or ""),
        ))
        for item in group:
            item["duplicate_group"] = True
            item["canonical_candidate"] = item is winner
            if item is not winner:
                item["superseded_by"] = {
                    "mod_id": winner.get("mod_id"),
                    "nexus_slug": winner.get("nexus_slug"),
                    "version": winner.get("version", ""),
                    "updated": winner.get("updated_time")
                               or winner.get("updated", ""),
                }
    return sorted(results, key=lambda item: (
        not item.get("canonical_candidate", False),
        -timestamp(item),
    ))


def _search_api(query: str, game_slug: str, api_key: str, game_id: int) -> list[dict]:
    """用 /mods/updated.json 拿全量 mod_id → 本地缓存 → 按名称匹配 → 补全详情。"""
    cache_key = f"{game_slug}_{game_id}"
    now = time.time()

    if cache_key in _MOD_CACHE:
        ts, mods = _MOD_CACHE[cache_key]
        if now - ts < 3600:
            return _match_and_detail(query, mods, game_slug, api_key)

    try:
        url = f"https://api.nexusmods.com/v1/games/{game_slug}/mods/updated.json?game_id={game_id}&period=1m"
        data = _api(url, api_key)

        mods = []
        for item in (data if isinstance(data, list) else data.get("data", [])):
            mod_id = item.get("mod_id") or item.get("id")
            if mod_id:
                mods.append({"mod_id": int(mod_id)})

        if mods:
            if len(_MOD_CACHE) >= _MOD_CACHE_MAX:
                oldest = min(_MOD_CACHE, key=lambda k: _MOD_CACHE[k][0])
                del _MOD_CACHE[oldest]
            _MOD_CACHE[cache_key] = (now, mods)
            return _match_and_detail(query, mods, game_slug, api_key)
    except urllib.error.HTTPError as exc:
        status = "authentication_failed" if exc.code in (401, 403) else "source_unavailable"
        raise NexusSearchUnavailable(status, f"Nexus API HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise NexusSearchUnavailable(
            "source_unavailable",
            f"无法连接 Nexus API: {getattr(exc, 'reason', exc)}",
        ) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise NexusSearchUnavailable(
            "invalid_response", f"Nexus API 返回无法解析的数据: {exc}"
        ) from exc

    return []


def _match_and_detail(query: str, mods: list, game_slug: str, api_key: str) -> list[dict]:
    """从缓存的 mod_id 列表中按名称匹配，补全详情。"""
    import concurrent.futures as cf

    broad_words = {
        "latest", "popular", "trending", "new", "hot", "best", "recommended",
        "mods", "mod", "最近", "最新", "热门", "推荐",
    }
    cleaned_query = query.casefold()
    for word in broad_words:
        cleaned_query = cleaned_query.replace(word, " ")
    wanted = {
        token for token in re.findall(r"[a-z0-9\u3400-\u9fff]+", cleaned_query)
        if len(token) >= 2
    }
    candidates = mods[:16]

    def fetch(m):
        try:
            detail = get_mod(m["mod_id"], game_slug, api_key)
            haystack = " ".join([
                str(detail.get("name") or ""),
                str(detail.get("summary") or ""),
            ]).casefold()
            compact = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", haystack)
            score = sum(1 for token in wanted if token in haystack or token in compact)
            return score, {
                "mod_id": m["mod_id"],
                "name": detail.get("name", ""),
                "summary": detail.get("summary", ""),
                "endorsements": detail.get("endorsement_count", 0),
                "version": detail.get("version", ""),
                "updated": detail.get("updated_time", ""),
            }
        except Exception:
            return -1, None

    pool = cf.ThreadPoolExecutor(max_workers=min(8, len(candidates) or 1))
    futures = [pool.submit(fetch, candidate) for candidate in candidates]
    rows = []
    for future in cf.as_completed(futures):
        score, item = future.result()
        if item and (not wanted or score > 0):
            rows.append((score, item))
    pool.shutdown(wait=True)
    rows.sort(key=lambda pair: (
        pair[0],
        pair[1].get("endorsements") or 0,
        pair[1].get("updated") or "",
    ), reverse=True)
    return [item for _, item in rows[:10]]


def _search_cdp(query: str, game_slug: str, api_key: str, cdp_port: int, game_id: int) -> list[dict]:
    """CDP 搜索作为回退。"""
    try:
        import asyncio
        from . import downloader
        results = asyncio.run(downloader.search_via_cdp(query, game_slug, game_id, cdp_port))
        return results
    except RuntimeError as e:
        return [{"name": f"浏览器自动化不可用: {e}", "mod_id": 0, "error": str(e)}]
    except Exception as e:
        return [{"name": f"搜索失败: {e}", "mod_id": 0, "error": str(e)}]


def get_mod(mod_id: int, game_slug: str, api_key: str, cdp_port: int = 18888) -> dict:
    try:
        return _api(f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{mod_id}.json", api_key)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # 成人/受限内容 API 被拒 → 用已登录 Chrome 抓页面兜底
            info = _get_mod_via_cdp(mod_id, game_slug, cdp_port)
            if info:
                return info
            raise RuntimeError(f"获取 Mod {mod_id} 详情失败：HTTP {e.code}（成人内容受 API 限制；如已在 ModAgent 浏览器登录 Nexus 仍失败，可直接用 mod_id 下载）")
        raise


def _get_mod_via_cdp(mod_id: int, game_slug: str, cdp_port: int) -> Optional[dict]:
    try:
        import asyncio
        from . import downloader
        return asyncio.run(downloader.fetch_mod_page_cdp(mod_id, game_slug, cdp_port))
    except Exception:
        return None


def get_mod_files(mod_id: int, game_slug: str, api_key: str) -> list[dict]:
    data = _api(f"https://api.nexusmods.com/v1/games/{game_slug}/mods/{mod_id}/files.json", api_key)
    return data.get("files", [])


def get_main_file(mod_id: int, game_slug: str, api_key: str) -> Optional[dict]:
    files = get_mod_files(mod_id, game_slug, api_key)
    for f in files:
        if f.get("category_name") == "MAIN":
            return f
    return files[0] if files else None


def _staleness(updated_iso, threshold_months: int = 12) -> dict:
    """据 Nexus updated_time(ISO 8601)判断 mod 陈旧程度 → 安装前预警。
    Basic MiniMap 那类:2024 的 mod 跟不上高频更新的游戏,装了 ModClass 加载失败不生效。
    解析失败/无时间返回 None,绝不阻塞。"""
    if not updated_iso:
        return None
    import time as _t, datetime as _dt
    try:
        d = _dt.datetime.fromisoformat(str(updated_iso).replace("Z", "+00:00"))
        months = (_t.time() - d.timestamp()) / (30 * 86400)
    except Exception:
        return None
    m = max(0, int(months))
    if m >= threshold_months:
        return {"months_ago": m, "stale": True,
                "note": f"该 mod 最后更新于约 {m} 个月前,可能不兼容当前游戏版本"
                        "(高频更新的游戏如 Palworld 尤甚),装了不生效的风险较高——"
                        "装前请留意,不生效就找更新更近的替代。"}
    return {"months_ago": m, "stale": False}


def get_detail(mod_id: int, game_slug: str, api_key: str, cdp_port: int = 18888) -> dict:
    mod = get_mod(mod_id, game_slug, api_key, cdp_port)
    try:
        main = get_main_file(mod_id, game_slug, api_key)
    except Exception:
        main = None
    deps = [d.get("mod_id") for d in mod.get("dependencies", []) if d.get("mod_id")]
    dependency_labels = _extract_dependency_labels(mod.get("description", ""))
    required_loader = _extract_required_loader(
        mod.get("description", ""),
        dependency_labels,
        mod.get("name", ""),
    )

    return {
        "mod_id": mod.get("mod_id", mod_id),
        "name": mod.get("name", ""),
        "summary": mod.get("summary", ""),
        "description": mod.get("description", "")[:2000],
        "version": main.get("version", mod.get("version", "?")) if main else mod.get("version", "?"),
        "file_id": main.get("file_id") if main else None,
        "file_name": main.get("file_name", "") if main else "",
        "file_size_kb": main.get("size_kb", 0) if main else 0,
        "endorsements": mod.get("endorsement_count", 0),
        "downloads": mod.get("mod_downloads", 0),
        "author": mod.get("author", ""),
        "category": mod.get("category", ""),
        "updated_at": mod.get("updated_time", ""),
        "staleness": _staleness(mod.get("updated_time", "")),
        "dependencies": deps,
        "dependency_labels": dependency_labels,
        "required_loader": required_loader,
        "install_notes": _extract_install_notes(mod.get("description", "")),
    }


def get_description(mod_id: int, game_slug: str, api_key: str, cdp_port: int = 18888) -> str:
    mod = get_mod(mod_id, game_slug, api_key, cdp_port)
    return mod.get("description", "") or mod.get("summary", "")


def get_mod_description(mod_id: int, game_slug: str, api_key: str, cdp_port: int = 18888) -> dict:
    desc = get_description(mod_id, game_slug, api_key, cdp_port)
    return _parse_readme(desc)


def resolve_deps(mod_id: int, game_slug: str, api_key: str) -> list[int]:
    mod = get_mod(mod_id, game_slug, api_key)
    return [d.get("mod_id") for d in mod.get("dependencies", []) if d.get("mod_id")]


def _extract_install_notes(desc: str) -> str:
    if not desc:
        return ""
    lines = desc.split("\n")
    notes = []
    in_install = False
    for line in lines:
        lower = line.strip().lower()
        if any(kw in lower for kw in ["installation", "install", "how to install", "usage"]):
            in_install = True
            continue
        if in_install and lower.startswith("#"):
            break
        if in_install and line.strip():
            notes.append(line.strip())
    return "\n".join(notes[:10]) if notes else ""


def _source_plain_text(value: str) -> str:
    """Convert the small HTML/BBCode subset used by Nexus descriptions."""
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:p|div|li|ul|ol|h[1-6])\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\*\]", "\n* ", text, flags=re.I)
    text = re.sub(r"\[url=[^\]]+\](.*?)\[/url\]", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"\[/?(?:b|i|u|size|color|font|list)(?:=[^\]]+)?\]", "", text, flags=re.I)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _extract_dependency_labels(desc: str) -> list[str]:
    """Extract explicitly required dependency names from source prose.

    Nexus' structured dependency array is frequently empty even when the
    description contains a clear "required dependencies" section.  Only that
    explicit section is accepted here; incidental framework mentions do not
    become hard requirements.
    """
    plain = _source_plain_text(desc)
    if not plain:
        return []
    marker = re.search(
        r"(?:required\s+dependencies|requirements?|必需(?:依赖|前置)|前置依赖)"
        r"(?:\s+(?:installed|安装))?\s*:?",
        plain,
        flags=re.I,
    )
    if not marker:
        return []
    section = plain[marker.end():marker.end() + 900]
    stop = re.search(
        r"\n\s*\*?\s*(?:launch|usage|configuration|optional|credits?|"
        r"how\s+to\s+use|启动|使用|配置)\b",
        section,
        flags=re.I,
    )
    if stop:
        section = section[:stop.start()]

    labels = []
    for raw in re.findall(r"(?:^|\n)\s*\*\s*([^\n]+)", section):
        label = raw.strip(" :-–—\t")
        label = re.split(r"\s{2,}|[（(](?:optional|可选)", label, maxsplit=1, flags=re.I)[0]
        if (
            label
            and len(label) <= 80
            and label.casefold() not in {"download", "extract", "install"}
            and label not in labels
        ):
            labels.append(label)
    return labels[:12]


def _extract_required_loader(
    desc: str,
    dependency_labels: list[str] | None = None,
    name: str = "",
) -> str:
    labels = {
        re.sub(r"[^a-z0-9]+", "", str(label).casefold())
        for label in (dependency_labels or [])
    }
    if "melonloader" in labels:
        return "MelonLoader"
    if "bepinex" in labels or "bepinexpack" in labels:
        return "BepInEx"

    plain = _source_plain_text(desc)
    title = _source_plain_text(name)
    if re.search(r"(?:^|[\s(\[])BepInEx(?:Pack)?(?:[\s)\]]|$)", title, flags=re.I):
        return "BepInEx"
    if re.search(r"(?:^|[\s(\[])MelonLoader(?:[\s)\]]|$)", title, flags=re.I):
        return "MelonLoader"
    strong_patterns = (
        (r"\bport(?:ed)?\b.{0,100}\bto\s+MelonLoader\b", "MelonLoader"),
        (r"\b(?:requires?|built\s+for|made\s+for)\s+MelonLoader\b", "MelonLoader"),
        (r"\bMelonLoader[\\/](?:Mods|UserData)\b", "MelonLoader"),
        (r"\bport(?:ed)?\b.{0,100}\bto\s+BepInEx\b", "BepInEx"),
        (r"\b(?:requires?|built\s+for|made\s+for)\s+BepInEx(?:Pack)?\b", "BepInEx"),
        (r"\bBepInEx[\\/](?:plugins|patchers|config)\b", "BepInEx"),
    )
    for pattern, loader in strong_patterns:
        if re.search(pattern, plain, flags=re.I | re.S):
            return loader
    return ""


def _parse_readme(desc: str) -> dict:
    result = {"dependencies": [], "install_paths": [], "warnings": [], "uninstall_method": ""}
    if not desc:
        return result

    lower = desc.lower()

    if "extract to" in lower or "drop into" in lower or "place in" in lower:
        for line in desc.split("\n"):
            if any(kw in line.lower() for kw in ["extract to", "drop into", "place in", "copy to", "install to"]):
                result["install_paths"].append(line.strip()[:120])

    for line in desc.split("\n"):
        if any(kw in line.lower() for kw in ["require", "dependency", "need", "prerequisite"]):
            result["dependencies"].append(line.strip()[:120])

    for line in desc.split("\n"):
        if any(kw in line.lower() for kw in ["warning", "caution", "important", "note:", "compatib"]):
            result["warnings"].append(line.strip()[:120])

    return result
