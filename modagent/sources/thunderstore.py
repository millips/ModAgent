"""Thunderstore 适配器：Unity/BepInEx 游戏（雨中冒险2、Lethal Company、Valheim、REPO 等）。
包格式标准化、API 全公开、无需认证/登录/浏览器。"""
import gzip
import json
import os
import re
import time
from datetime import datetime, timezone
from math import log10

from . import _http_json, _safe, _dest
from .. import downloader
from ..config import CONFIG_DIR

_COMMUNITIES = None              # 缓存社区列表
_PKG_CACHE = {}                  # community -> (ts, packages)
_PKG_TTL = 600                   # 包列表缓存 10 分钟
_DISK_PKG_TTL = 24 * 3600        # 初次全量目录较大，跨进程复用一天
_COMMUNITY_HINTS = {
    "repo": "repo",
    "lethalcompany": "lethal-company",
    "riskofrain2": "riskofrain2",
    "valheim": "valheim",
}


_SEARCH_ALIASES = {
    "map": {
        "map", "maps", "radar", "navigation", "navigator",
        "地图", "雷达", "导航",
    },
    "minimap": {
        "minimap", "mini map", "小地图",
    },
    "player": {
        "player", "players", "teammate", "teammates", "team", "teams",
        "spectator", "spectators", "multiplayer", "coop", "co op",
        "玩家", "队友", "队伍", "多人", "联机",
    },
    "enemy": {
        "enemy", "enemies", "monster", "monsters", "creature", "creatures",
        "敌人", "敌怪", "怪物",
    },
    "item": {
        "item", "items", "valuable", "valuables", "loot",
        "物品", "道具", "战利品", "贵重物",
    },
    "inventory": {
        "inventory", "inventories", "slot", "slots", "backpack",
        "背包", "物品栏", "格子", "槽位",
    },
    "upgrade": {
        "upgrade", "upgrades", "level", "levels",
        "升级", "强化", "等级",
    },
    "revive": {
        "revive", "revival", "resurrect", "respawn",
        "复活", "救援", "重生",
    },
    "health": {
        "health", "heal", "healing", "hp", "life",
        "生命", "血量", "治疗", "回血",
    },
    "stamina": {
        "stamina", "sprint", "running", "run",
        "体力", "耐力", "冲刺", "奔跑",
    },
    "cosmetic": {
        "cosmetic", "cosmetics", "skin", "skins", "appearance",
        "外观", "皮肤", "装饰",
    },
}


def _staleness(updated_at: str, threshold_days: int = 365) -> dict:
    """Return an honest compatibility-risk hint, never a compatibility claim."""
    text = str(updated_at or "").strip()
    if not text:
        return {
            "stale": None,
            "age_days": None,
            "note": "来源未提供更新时间，无法据此核验当前游戏版本兼容性",
        }
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - value).days)
    except (TypeError, ValueError):
        return {
            "stale": None,
            "age_days": None,
            "note": "来源更新时间无法解析，当前游戏版本兼容性待核验",
        }
    stale = age_days > threshold_days
    return {
        "stale": stale,
        "age_days": age_days,
        "note": (
            f"约 {max(1, age_days // 30)} 个月未更新，未找到适配当前游戏版本的机器可读证据"
            if stale else
            "近期仍有更新，但 Thunderstore 未声明支持的具体游戏构建版本"
        ),
    }
_SEARCH_STOPWORDS = {
    "a", "an", "and", "the", "for", "from", "in", "of", "on", "or", "to",
    "with", "mod", "mods", "repo", "r", "e", "p", "o", "find", "search",
    "show", "display", "add", "adds", "please", "want", "need",
}
_SEARCH_NEGATIONS = {
    "no", "not", "never", "without", "disable", "disables", "remove",
    "removes", "不", "不会", "没有", "无", "禁用", "移除",
}


def _search_text(value: str) -> str:
    """Normalize package/query text while preserving CJK search terms."""
    text = str(value or "")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", " ", text).lower()
    return " ".join(text.split())


def _public_summary(value: str, limit: int = 140) -> str:
    """Keep feature prose while excluding contact/group promotion."""
    text = str(value or "")
    patterns = (
        r"(?:\b[A-Z0-9_.-]+\s*)?游戏(?:交流|讨论)?\s*QQ\s*群"
        r"(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
        r"加入\s*QQ\s*群(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
        r"QQ\s*群(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _query_concepts(query: str) -> list[tuple[str, set[str]]]:
    """Turn natural search text into de-duplicated semantic search groups."""
    normalized = _search_text(query)
    raw_lower = str(query or "").lower()
    token_to_concept = {}
    for concept, aliases in _SEARCH_ALIASES.items():
        for alias in aliases:
            token_to_concept[_search_text(alias)] = concept

    concepts = []
    seen = set()
    for concept, aliases in _SEARCH_ALIASES.items():
        if (
            concept == "map"
            and "小地图" in raw_lower
            and raw_lower.count("地图") == raw_lower.count("小地图")
        ):
            continue
        if any(
            any("\u3400" <= char <= "\u9fff" for char in alias)
            and alias in raw_lower
            for alias in aliases
        ):
            concepts.append((concept, aliases))
            seen.add(concept)

    for token in normalized.split():
        if token in _SEARCH_STOPWORDS or len(token) < 2:
            continue
        concept = token_to_concept.get(token, token)
        if (
            concept == token
            and any("\u3400" <= char <= "\u9fff" for char in token)
            and seen
        ):
            # A continuous Chinese sentence is context for the known concepts
            # found above, not an additional literal term to require.
            continue
        if concept in seen:
            continue
        aliases = _SEARCH_ALIASES.get(concept, {token})
        concepts.append((concept, aliases))
        seen.add(concept)
    return concepts


def _contains_alias(normalized: str, aliases: set[str]) -> bool:
    tokens = normalized.split()
    for alias in aliases:
        alias_tokens = _search_text(alias).split()
        if not alias_tokens:
            continue
        width = len(alias_tokens)
        for index in range(0, len(tokens) - width + 1):
            if tokens[index:index + width] != alias_tokens:
                continue
            context = tokens[max(0, index - 3):index]
            if any(token in _SEARCH_NEGATIONS for token in context):
                continue
            return True
    return False


def _package_search_score(package: dict, query: str) -> dict | None:
    """Score a package by concept coverage, field quality and popularity."""
    versions = package.get("versions") or [{}]
    description = versions[0].get("description", "") if versions else ""
    name = _search_text(package.get("name", ""))
    owner = _search_text(package.get("owner", ""))
    desc = _search_text(description)
    concepts = _query_concepts(query)
    literal_query_tokens = {
        token for token in _search_text(query).split()
        if token not in _SEARCH_STOPWORDS and len(token) >= 2
    }
    literal_name_hits = len(literal_query_tokens.intersection(name.split()))
    downloads = package.get("total_downloads") or sum(
        version.get("downloads", 0) for version in versions
    )

    if not concepts:
        return {
            "score": log10(max(0, downloads) + 1),
            "coverage": 1.0,
            "matched": [],
            "missing": [],
            "weak_matches": [],
            "intent_penalties": [],
            "name_hits": 0,
            "literal_name_hits": 0,
            "mode": "browse",
        }

    matched = []
    missing = []
    weak_matches = []
    name_hits = 0
    score = 0.0
    matched_weight = 0.0
    for concept, aliases in concepts:
        field_score = 0
        if _contains_alias(name, aliases):
            field_score = 20
            name_hits += 1
        elif _contains_alias(desc, aliases):
            field_score = 8
        elif _contains_alias(owner, aliases):
            field_score = 3
        weak = False
        if not field_score and concept in {"map", "minimap"}:
            sibling = "map" if concept == "minimap" else "minimap"
            weak_aliases = _SEARCH_ALIASES[sibling]
            if _contains_alias(name, weak_aliases):
                field_score = 10
                name_hits += 1
                weak = True
            elif _contains_alias(desc, weak_aliases):
                field_score = 4
                weak = True
        if field_score:
            matched.append(concept)
            score += field_score
            matched_weight += 0.5 if weak else 1.0
            if weak:
                weak_matches.append(concept)
        else:
            missing.append(concept)

    if not matched:
        return None

    coverage = matched_weight / len(concepts)
    concept_names = {concept for concept, _aliases in concepts}
    intent_penalties = []
    package_text = f"{name} {desc}"
    if (
        "minimap" in concept_names
        and "upgrade" not in concept_names
        and "count" not in concept_names
        and (
            " upgrade " in f" {package_text} "
            or " upgrades " in f" {package_text} "
            or " player count " in f" {package_text} "
        )
    ):
        intent_penalties.append("unsolicited_upgrade_or_player_count")
        coverage = max(0.0, coverage - 0.34)
        score -= 20
    score += (
        coverage * 30
        + literal_name_hits * 6
        + min(7.0, log10(max(0, downloads) + 1))
    )
    return {
        "score": round(score, 3),
        "coverage": round(coverage, 3),
        "matched": matched,
        "missing": missing,
        "weak_matches": weak_matches,
        "intent_penalties": intent_penalties,
        "name_hits": name_hits,
        "literal_name_hits": literal_name_hits,
        "mode": (
            "strict"
            if not missing and not weak_matches and not intent_penalties
            else "relaxed"
        ),
    }


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


def community_hint(game_name: str = "", game_slug: str = "") -> str:
    """Resolve well-known community identifiers without a network round trip."""
    for value in (game_slug, game_name):
        normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
        if normalized in _COMMUNITY_HINTS:
            return _COMMUNITY_HINTS[normalized]
    return ""


def _catalog_cache_path(community: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "-", str(community or "").casefold()).strip("-")
    return os.path.join(CONFIG_DIR, "cache", f"thunderstore-{safe or 'unknown'}.json.gz")


def _load_disk_catalog(community: str, allow_stale: bool = False) -> list | None:
    path = _catalog_cache_path(community)
    try:
        if not allow_stale and time.time() - os.path.getmtime(path) > _DISK_PKG_TTL:
            return None
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, list) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_disk_catalog(community: str, packages: list) -> None:
    path = _catalog_cache_path(community)
    temp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(packages, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp, path)
    except OSError:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass


def _packages(
    community: str, force_refresh: bool = False, cancel_check=None,
) -> list:
    now = time.time()
    cached = _PKG_CACHE.get(community)
    if not force_refresh and cached and now - cached[0] < _PKG_TTL:
        return cached[1]
    if not force_refresh:
        disk_cached = _load_disk_catalog(community)
        if disk_cached is not None:
            _PKG_CACHE[community] = (now, disk_cached)
            return disk_cached
    url = f"https://thunderstore.io/c/{community}/api/v1/package/"
    try:
        pkgs = _http_json(url, total_timeout=75, cancel_check=cancel_check)
    except TypeError as exc:
        # A few integrations/tests replace the transport with a minimal
        # one-argument callable. Keep that extension point compatible.
        if "unexpected keyword argument" not in str(exc):
            raise
        pkgs = _http_json(url)
    except Exception as first_error:
        # A transient TLS/proxy handshake must not turn a locally usable
        # catalogue into a hard "no results" state. Retry once quickly, then
        # retain a stale local catalogue for read-only search if one exists.
        try:
            time.sleep(0.6)
            pkgs = _http_json(url, total_timeout=75, cancel_check=cancel_check)
        except Exception:
            stale_catalog = _load_disk_catalog(community, allow_stale=True)
            if stale_catalog is not None:
                _PKG_CACHE[community] = (now, stale_catalog)
                return stale_catalog
            raise first_error
    if not isinstance(pkgs, list):
        raise RuntimeError("Thunderstore package API returned an invalid response")
    _PKG_CACHE[community] = (now, pkgs)
    _save_disk_catalog(community, pkgs)
    return pkgs


def list_packages(
    community: str, force_refresh: bool = False, cancel_check=None,
) -> list:
    """Return the complete community package ledger for identity matching."""
    return list(_packages(
        community, force_refresh=force_refresh, cancel_check=cancel_check,
    ))


def get_package(namespace: str, name: str, *, cancel_check=None) -> dict:
    """Fetch one known package directly; this avoids the full community ledger."""
    namespace = str(namespace or "").strip()
    name = str(name or "").strip()
    if not namespace or not name:
        raise ValueError("Thunderstore package identity is incomplete")
    url = f"https://thunderstore.io/api/experimental/package/{namespace}/{name}/"
    try:
        return _http_json(
            url, total_timeout=30, cancel_check=cancel_check,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return _http_json(url)


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
    updated_at = (
        latest.get("date_created")
        or latest.get("datetime_created")
        or latest.get("created_at")
        or ""
    )
    dest = _dest(game_slug, f"ts_{_safe(ns)}_{_safe(name)}_{_safe(ver)}.zip")
    downloader.download_file(dlurl, dest, progress_callback)
    return {
        "local_path": dest,
        "name": f"{ns}-{name}",
        "source": "thunderstore",
        "version": ver,
        "dependencies": latest.get("dependencies") or [],
        "updated_at": updated_at,
        "detail_verified": True,
        "verification_source": "thunderstore_package_api",
        "deprecated": bool(data.get("is_deprecated")),
        "staleness": _staleness(updated_at),
    }


def search(community: str, query: str, limit: int = 12,
           force_refresh: bool = False) -> list:
    """在某社区(=游戏)的包列表里按名称/作者/简介搜，按下载量排序。"""
    pkgs = _packages(community, force_refresh=force_refresh)
    out = []
    for p in pkgs:
        versions = p.get("versions") or [{}]
        desc = versions[0].get("description", "") if versions else ""
        match = _package_search_score(p, query)
        if match:
            # v1 接口下载量在各版本里，累加得总量
            dl = p.get("total_downloads") or sum(v.get("downloads", 0) for v in versions)
            out.append({
                "name": p.get("name", ""),
                "full_name": p.get("full_name", ""),
                "url": p.get("package_url", ""),
                "summary": _public_summary(desc),
                "downloads": dl,
                "pinned": p.get("is_pinned", False),
                "owner": p.get("owner", ""),
                "latest_version": str(versions[0].get("version_number", "")) if versions else "",
                "updated_at": (
                    versions[0].get("date_created")
                    or versions[0].get("datetime_created")
                    or versions[0].get("created_at")
                    or ""
                    if versions else ""
                ),
                "staleness": _staleness(
                    (
                        versions[0].get("date_created")
                        or versions[0].get("datetime_created")
                        or versions[0].get("created_at")
                        or ""
                    ) if versions else ""
                ),
                "deprecated": bool(p.get("is_deprecated")),
                "dependencies": (
                    versions[0].get("dependencies") or []
                    if versions else []
                ),
                "has_files": bool(
                    versions and versions[0].get("download_url")
                ),
                "_detail_verified": bool(versions),
                "verification_source": "thunderstore_catalog",
                "search_match": match,
            })
    out.sort(
        key=lambda item: (
            item["search_match"]["coverage"],
            item["search_match"]["literal_name_hits"],
            item["search_match"]["name_hits"],
            item["search_match"]["score"],
            item["downloads"],
        ),
        reverse=True,
    )
    return out[:limit]
