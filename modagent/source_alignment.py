"""Bind locally discovered mods to stable upstream package identities."""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

from . import db, nexus
from .sources import thunderstore


_GENERIC_PARTS = {
    "bepinex", "plugins", "plugin", "mods", "mod", "patchers", "config",
    "repo", "release", "latest", "unknown", "src", "local", "custom", "ts",
}
_VERSION_RE = re.compile(r"(?:^|[_\-\s])v?\d+(?:[._-]\d+){1,4}(?:$|[_\-\s])", re.I)


def normalize_name(value: str) -> str:
    value = _VERSION_RE.sub(" ", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _local_aliases(mod) -> set[str]:
    raw = {str(mod.name or "")}
    try:
        files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
    except Exception:
        files = []
    for value in files[:200]:
        path = str(value or "").rstrip("\\/")
        if not path:
            continue
        raw.add(os.path.splitext(os.path.basename(path))[0])
        raw.add(os.path.basename(os.path.dirname(path)))
    aliases = set()
    for value in raw:
        normalized = normalize_name(value)
        if len(normalized) >= 4 and normalized not in _GENERIC_PARTS:
            aliases.add(normalized)
    return aliases


def _latest(package: dict) -> tuple[str, dict]:
    versions = package.get("versions") or []
    latest = versions[0] if versions and isinstance(versions[0], dict) else {}
    return str(latest.get("version_number") or ""), latest


def _package_row(package: dict) -> dict:
    latest_version, latest = _latest(package)
    owner = str(package.get("owner") or "")
    name = str(package.get("name") or "")
    full_name = str(package.get("full_name") or f"{owner}-{name}").strip("-")
    return {
        "name": name,
        "owner": owner,
        "full_name": full_name,
        "source_key": full_name,
        "url": str(package.get("package_url") or ""),
        "latest_version": latest_version,
        "description": str(latest.get("description") or "")[:240],
        "downloads": int(package.get("total_downloads") or sum(
            int(item.get("downloads") or 0)
            for item in (package.get("versions") or [])
            if isinstance(item, dict)
        )),
        "_normalized": normalize_name(name),
        "_full_normalized": normalize_name(full_name),
    }


def _score(aliases: set[str], package: dict) -> float:
    package_names = {
        package.get("_normalized") or "",
        package.get("_full_normalized") or "",
    } - {""}
    best = 0.0
    for alias in aliases:
        for candidate in package_names:
            if alias == candidate:
                return 1.0
            # Source-downloaded archives often produce names such as
            # ts_Author_Package_1.2.3. Containment is reliable when the
            # actual package name is not a tiny generic token.
            short, long = sorted((alias, candidate), key=len)
            if len(short) >= 5 and short in long:
                best = max(best, .97 if short == package.get("_normalized") else .94)
            best = max(best, SequenceMatcher(None, alias, candidate).ratio())
    return round(best, 4)


def _public_candidate(row: dict, score: float) -> dict:
    return {
        key: value for key, value in row.items()
        if not key.startswith("_")
    } | {"score": score}


def align_installed_mods(cfg, *, force_refresh: bool = False) -> dict:
    """Auto-bind current-game mods and report safe/ambiguous/unmatched rows."""
    slug = str(getattr(cfg, "game_slug", "") or "")
    mods = db.get_installed_mods(slug)
    report = {
        "game_slug": slug,
        "community": "",
        "total": len(mods),
        "bound": [],
        "ambiguous": [],
        "unmatched": [],
        "source_errors": [],
    }
    if not mods:
        report["summary"] = {"bound": 0, "ambiguous": 0, "unmatched": 0}
        return report

    # IDs already controlled by Nexus/Steam are stable and need no fuzzy match.
    pending = []
    for mod in mods:
        mid = str(mod.id)
        if mid.isdigit():
            url = f"https://www.nexusmods.com/{slug}/mods/{mid}" if slug else ""
            db.upsert_mod_source_binding(
                slug, mid, "nexus", mid, url, 1, "stable_id", mod.version,
            )
            report["bound"].append({
                "mod_id": mid, "name": mod.name, "source": "nexus",
                "source_key": mid, "confidence": 1, "match_method": "stable_id",
                "current_version": mod.version, "latest_version": "",
                "url": url,
            })
        elif mid.startswith("ws_"):
            workshop_id = mid[3:]
            db.upsert_mod_source_binding(
                slug, mid, "workshop", workshop_id, "", 1, "stable_id", mod.version,
            )
            report["bound"].append({
                "mod_id": mid, "name": mod.name, "source": "workshop",
                "source_key": workshop_id, "confidence": 1, "match_method": "stable_id",
                "current_version": mod.version, "latest_version": "",
                "url": "",
            })
        else:
            existing = db.get_mod_source_binding(mid, slug)
            if existing and existing.get("match_method") == "manual":
                report["bound"].append({
                    "mod_id": mid, "name": mod.name, "source": existing["source"],
                    "source_key": existing["source_key"],
                    "confidence": existing["confidence"], "match_method": "manual",
                    "current_version": mod.version,
                    "latest_version": existing.get("latest_version") or "",
                    "url": existing.get("source_url") or "",
                })
            else:
                pending.append(mod)

    # First try Nexus for locally imported rows. This is intentionally separate
    # from disk scanning: a slow/failed website can never make installed files
    # disappear. Tavily-backed matching may run in parallel; CDP matching is
    # serialized because one browser tab set is not concurrency-safe.
    nexus_slug = slug if slug and not slug.startswith("local_") else ""
    try:
        preferred_community = thunderstore.find_community(
            getattr(cfg, "game_name", "") or ""
        )
    except Exception:
        preferred_community = ""
    # Thunderstore ecosystems expose a complete package catalogue and should
    # use that deterministic bulk match. Per-name Nexus search is reserved for
    # games without such a catalogue (Cyberpunk, Stellar Blade, etc.).
    if pending and nexus_slug and not preferred_community:
        tavily_key = str(getattr(cfg, "tavily_api_key", "") or "")
        api_key = str(getattr(cfg, "nexus_api_key", "") or "")
        cdp_port = int(getattr(cfg, "chrome_cdp_port", 18888) or 18888)

        def nexus_candidates(mod):
            try:
                rows = nexus.search(
                    mod.name, nexus_slug, api_key, cdp_port=cdp_port,
                    game_id=int(getattr(cfg, "game_id", 0) or 0),
                    tavily_key=tavily_key,
                )
                return mod, [row for row in rows if row.get("mod_id")], ""
            except Exception as exc:
                return mod, [], (str(exc) or type(exc).__name__)[:180]

        resolved = []
        if tavily_key and len(pending) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(6, len(pending)),
                                    thread_name_prefix="nexus-align") as pool:
                futures = [pool.submit(nexus_candidates, mod) for mod in pending]
                for future in as_completed(futures):
                    resolved.append(future.result())
        else:
            resolved = [nexus_candidates(mod) for mod in pending]

        claimed = {
            str(item.get("source_key"))
            for item in db.get_mod_source_bindings(slug)
            if item.get("source") == "nexus"
        }
        still_pending = []
        nexus_errors = []
        for mod, rows, error in resolved:
            aliases = _local_aliases(mod)
            ranked = []
            for row in rows[:10]:
                candidate = {
                    "_normalized": normalize_name(row.get("name", "")),
                    "_full_normalized": normalize_name(row.get("name", "")),
                }
                ranked.append((_score(aliases, candidate), row))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            best_score, best = ranked[0] if ranked else (0.0, {})
            runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
            source_key = str(best.get("mod_id") or "")
            exact = best_score == 1.0
            strong = best_score >= .92 and best_score - runner_up >= .06
            if source_key and source_key not in claimed and (exact or strong):
                url = f"https://www.nexusmods.com/{nexus_slug}/mods/{source_key}"
                latest = str(best.get("version") or "")
                method = "exact_name" if exact else "strong_name"
                db.upsert_mod_source_binding(
                    slug, str(mod.id), "nexus", source_key, url,
                    best_score, method, latest,
                    {"nexus_slug": nexus_slug, "matched_name": best.get("name", "")},
                )
                claimed.add(source_key)
                report["bound"].append({
                    "mod_id": str(mod.id), "name": mod.name, "source": "nexus",
                    "source_key": source_key, "confidence": best_score,
                    "match_method": method, "current_version": mod.version,
                    "latest_version": latest, "url": url,
                })
            else:
                if error:
                    nexus_errors.append(error)
                still_pending.append(mod)
        pending = still_pending
        if nexus_errors:
            report["source_errors"].append({
                "source": "nexus",
                "error": f"{len(nexus_errors)} 项查询失败；已保留本地记录，可稍后重试",
            })

    packages = []
    if pending:
        try:
            community = thunderstore.find_community(getattr(cfg, "game_name", "") or "")
            report["community"] = community or ""
            if community:
                packages = [
                    _package_row(item)
                    for item in thunderstore.list_packages(
                        community, force_refresh=force_refresh
                    )
                ]
            else:
                report["source_errors"].append({
                    "source": "thunderstore",
                    "error": "未能匹配当前游戏的 Thunderstore 社区",
                })
        except Exception as exc:
            report["source_errors"].append({
                "source": "thunderstore", "error": str(exc)[:200],
            })

    for mod in pending:
        aliases = _local_aliases(mod)
        ranked = sorted(
            ((_score(aliases, package), package) for package in packages),
            key=lambda pair: (pair[0], pair[1].get("downloads", 0)),
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, {})
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        exact = best_score == 1.0
        strong = best_score >= .90 and best_score - runner_up >= .06
        base = {
            "mod_id": str(mod.id),
            "name": mod.name,
            "current_version": mod.version,
        }
        if best and (exact or strong):
            method = "exact_name" if exact else "strong_name"
            db.upsert_mod_source_binding(
                slug, str(mod.id), "thunderstore", best["source_key"],
                best["url"], best_score, method, best["latest_version"],
                {"community": report["community"], "owner": best["owner"],
                 "package_name": best["name"]},
            )
            report["bound"].append(base | {
                "source": "thunderstore",
                "source_key": best["source_key"],
                "url": best["url"],
                "latest_version": best["latest_version"],
                "confidence": best_score,
                "match_method": method,
            })
        elif best_score >= .58:
            report["ambiguous"].append(base | {
                "reason": "候选相似，但不足以安全自动绑定",
                "candidates": [
                    _public_candidate(row, score)
                    for score, row in ranked[:3] if score >= .45
                ],
            })
        else:
            report["unmatched"].append(base | {
                "reason": (
                    "来源查询失败，未执行名称判定"
                    if report["source_errors"] else
                    "Thunderstore 包清单中没有足够可信的名称匹配"
                ),
            })

    report["bound"].sort(key=lambda item: item["name"].casefold())
    report["ambiguous"].sort(key=lambda item: item["name"].casefold())
    report["unmatched"].sort(key=lambda item: item["name"].casefold())
    report["summary"] = {
        "bound": len(report["bound"]),
        "ambiguous": len(report["ambiguous"]),
        "unmatched": len(report["unmatched"]),
        "source_errors": len(report["source_errors"]),
    }
    return report
