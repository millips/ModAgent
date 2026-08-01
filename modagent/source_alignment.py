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
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_IDENTITY_QUALIFIERS = {
    "api", "bridge", "continued", "continuation", "enhanced", "extended",
    "extension", "fix", "fork", "helper", "legacy", "lib", "library", "lite",
    "patch", "plus", "redux", "remake", "rework", "revived", "toolkit",
}


def normalize_name(value: str) -> str:
    value = _VERSION_RE.sub(" ", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _identity_tokens(value: str) -> list[str]:
    """Preserve semantic suffixes that disappear in compact name matching."""
    value = _VERSION_RE.sub(" ", str(value or ""))
    value = _CAMEL_BOUNDARY_RE.sub(" ", value)
    return re.findall(r"[a-z0-9]+", value.casefold())


def _variant_conflict(local_name: str, candidate_name: str) -> bool:
    """Return True when two similar names identify different project variants."""
    local_normalized = normalize_name(local_name)
    candidate_normalized = normalize_name(candidate_name)
    if (
        not local_normalized
        or not candidate_normalized
        or local_normalized == candidate_normalized
    ):
        return False
    # Only use qualifier differences as a veto when the compact names overlap.
    # This catches MoreHead/MoreHeadBridge and MapValueTracker/Plus without
    # treating an unrelated author's prefix as identity evidence.
    if (
        local_normalized not in candidate_normalized
        and candidate_normalized not in local_normalized
    ):
        return False
    local_qualifiers = set(_identity_tokens(local_name)) & _IDENTITY_QUALIFIERS
    candidate_qualifiers = (
        set(_identity_tokens(candidate_name)) & _IDENTITY_QUALIFIERS
    )
    return local_qualifiers != candidate_qualifiers


def _binding_metadata(binding: dict | None) -> dict:
    raw = (binding or {}).get("metadata") or {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _binding_candidate_name(binding: dict | None) -> str:
    metadata = _binding_metadata(binding)
    candidate = str(
        metadata.get("package_name")
        or metadata.get("matched_name")
        or ""
    ).strip()
    if candidate:
        return candidate
    source_key = str((binding or {}).get("source_key") or "").strip()
    if (binding or {}).get("source") == "thunderstore" and "-" in source_key:
        return source_key.split("-", 1)[1]
    return ""


def _binding_requires_reaudit(mod, binding: dict | None) -> tuple[bool, str]:
    """Reject only unsafe name-derived bindings; stable/user IDs remain trusted."""
    method = str((binding or {}).get("match_method") or "").strip().casefold()
    if method not in {"exact_name", "strong_name"}:
        return False, ""
    candidate_name = _binding_candidate_name(binding)
    if candidate_name and _variant_conflict(str(mod.name or ""), candidate_name):
        return True, (
            f"本地名称“{mod.name}”与已绑定项目“{candidate_name}”包含不同变体后缀；"
            "旧名称推测已撤销，需重新核验稳定来源 ID"
        )
    return False, ""


def binding_reaudit_reason(mod, binding: dict | None) -> str:
    """Public guard for update paths that may run without bulk alignment."""
    required, reason = _binding_requires_reaudit(mod, binding)
    return reason if required else ""


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
        "source": "thunderstore",
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
                # Strict containment is a candidate hint, not identity proof:
                # MoreHeadBridge != MoreHead and MapValueTrackerPlus !=
                # MapValueTracker. Keep it below the automatic-bind threshold.
                best = max(best, .89 if short == package.get("_normalized") else .86)
                continue
            best = max(best, SequenceMatcher(None, alias, candidate).ratio())
    return round(best, 4)


def _public_candidate(row: dict, score: float) -> dict:
    return {
        key: value for key, value in row.items()
        if not key.startswith("_")
    } | {"score": score}


def _complete_binding(binding: dict | None) -> bool:
    """A usable binding needs both a stable identity and a public maintenance page.

    A legacy workshop row could contain only the Steam item ID.  Treating that
    as complete inflated the UI count and made the same Mod ineligible for
    sharing/update navigation.  Keep it pending so one normal alignment pass
    can repair the row with its canonical URL.
    """
    return bool(
        binding
        and str(binding.get("source") or "").strip()
        and str(binding.get("source_key") or "").strip()
        and str(binding.get("source_url") or "").strip()
    )


def alignment_pending_mods(
    cfg, *, mod_ids: list[str] | None = None, force_rebind: bool = False,
):
    """Return only rows that still need source identity work."""
    slug = str(getattr(cfg, "game_slug", "") or "")
    wanted = {str(value) for value in (mod_ids or []) if str(value)}
    mods = db.get_installed_mods(slug)
    if wanted:
        mods = [mod for mod in mods if str(mod.id) in wanted]
    if force_rebind:
        return mods
    bindings = {
        str(item.get("mod_id")): item
        for item in db.get_mod_source_bindings(slug)
    }
    return [
        mod for mod in mods
        if not _complete_binding(bindings.get(str(mod.id)))
    ]


def _finalize_report(report: dict) -> dict:
    for key in (
        "bound", "already_bound", "rejected_bindings", "ambiguous", "unmatched",
    ):
        report[key].sort(key=lambda item: str(item.get("name") or "").casefold())
    report["summary"] = {
        "bound": len(report["bound"]),
        "already_bound": len(report["already_bound"]),
        "rejected_bindings": len(report["rejected_bindings"]),
        "ambiguous": len(report["ambiguous"]),
        "unmatched": len(report["unmatched"]),
        "source_errors": len(report["source_errors"]),
        "cancelled": bool(report.get("cancelled")),
    }
    return report


def align_installed_mods(
    cfg, *, force_refresh: bool = False, progress_callback=None,
    mod_ids: list[str] | None = None, force_rebind: bool = False,
    cancel_check=None,
) -> dict:
    """Auto-bind current-game mods and report safe/ambiguous/unmatched rows."""
    slug = str(getattr(cfg, "game_slug", "") or "")
    mods = db.get_installed_mods(slug)
    wanted = {str(value) for value in (mod_ids or []) if str(value)}
    if wanted:
        mods = [mod for mod in mods if str(mod.id) in wanted]
    report = {
        "game_slug": slug,
        "community": "",
        "total": len(mods),
        "attempted": 0,
        "bound": [],
        "already_bound": [],
        "rejected_bindings": [],
        "ambiguous": [],
        "unmatched": [],
        "source_errors": [],
        "cancelled": False,
    }
    if not mods:
        report["summary"] = {
            "bound": 0, "already_bound": 0, "rejected_bindings": 0,
            "ambiguous": 0, "unmatched": 0,
        }
        return report

    progress_done: set[str] = set()

    def notify(mod, status: str, error: str = "") -> None:
        if not progress_callback:
            return
        mid = str(mod.id)
        if status in {"done", "failed"}:
            if mid in progress_done:
                return
            progress_done.add(mid)
        progress_callback(mid, status, error)

    def cancelled() -> bool:
        try:
            return bool(cancel_check and cancel_check())
        except Exception:
            return False

    # A completed source identity is persistent work. Re-running bulk alignment
    # must not search and bind it again; force_refresh only refreshes the remote
    # catalogue cache. An explicit force_rebind is required to reconsider it.
    existing_bindings = {
        str(item.get("mod_id")): item
        for item in db.get_mod_source_bindings(slug)
    }
    pending = []
    for mod in mods:
        mid = str(mod.id)
        existing = existing_bindings.get(mid)
        requires_reaudit, reaudit_reason = _binding_requires_reaudit(mod, existing)
        if requires_reaudit:
            db.delete_mod_source_binding(
                slug, mid, reason="unsafe_name_variant_binding",
            )
            report["rejected_bindings"].append({
                "mod_id": mid,
                "name": mod.name,
                "source": existing.get("source") or "",
                "source_key": existing.get("source_key") or "",
                "match_method": existing.get("match_method") or "",
                "reason": reaudit_reason,
            })
            existing = None
        if not force_rebind and _complete_binding(existing):
            report["already_bound"].append({
                "mod_id": mid,
                "name": mod.name,
                "source": existing.get("source") or "",
                "source_key": existing.get("source_key") or "",
                "confidence": existing.get("confidence") or 0,
                "match_method": existing.get("match_method") or "",
                "current_version": mod.version,
                "latest_version": existing.get("latest_version") or "",
                "url": existing.get("source_url") or "",
            })
            continue
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
            notify(mod, "done")
        elif mid.startswith("ws_"):
            workshop_id = mid[3:]
            url = (
                "https://steamcommunity.com/sharedfiles/filedetails/"
                f"?id={workshop_id}"
            )
            db.upsert_mod_source_binding(
                slug, mid, "workshop", workshop_id, url, 1, "stable_id", mod.version,
            )
            report["bound"].append({
                "mod_id": mid, "name": mod.name, "source": "workshop",
                "source_key": workshop_id, "confidence": 1, "match_method": "stable_id",
                "current_version": mod.version, "latest_version": "",
                "url": url,
            })
            notify(mod, "done")
        else:
            pending.append(mod)
    report["attempted"] = len(pending) + len(report["bound"])
    if cancelled():
        report["cancelled"] = True
        return _finalize_report(report)

    # First try Nexus for locally imported rows. This is intentionally separate
    # from disk scanning: a slow/failed website can never make installed files
    # disappear. Tavily-backed matching may run in parallel; CDP matching is
    # serialized because one browser tab set is not concurrency-safe.
    nexus_slug = slug if slug and not slug.startswith("local_") else ""
    try:
        preferred_community = thunderstore.community_hint(
            getattr(cfg, "game_name", "") or "", slug,
        ) or thunderstore.find_community(getattr(cfg, "game_name", "") or "")
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

        for mod in pending:
            notify(mod, "processing")
        resolved = []
        if tavily_key and len(pending) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(6, len(pending)),
                                    thread_name_prefix="nexus-align") as pool:
                futures = [pool.submit(nexus_candidates, mod) for mod in pending]
                for future in as_completed(futures):
                    if cancelled():
                        break
                    resolved.append(future.result())
        else:
            for mod in pending:
                if cancelled():
                    break
                resolved.append(nexus_candidates(mod))

        claimed = {
            str(item.get("source_key"))
            for item in db.get_mod_source_bindings(slug)
            if item.get("source") == "nexus"
        }
        still_pending = []
        nexus_errors = []
        for mod, rows, error in resolved:
            if cancelled():
                break
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
            credible = [
                (score, row) for score, row in ranked if score >= .90
            ]
            source_key = str(best.get("mod_id") or "")
            # An exact title is not identity proof when another highly similar
            # project exists. Auto Forager #7736/#47161 is the regression case.
            exact = (
                best_score == 1.0
                and len(credible) == 1
                and runner_up < .80
            )
            strong = (
                best_score >= .92
                and best_score - runner_up >= .06
                and len(credible) == 1
                and runner_up < .80
            )
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
                notify(mod, "done")
            elif best_score >= .58 and ranked:
                candidates = []
                for score, row in ranked[:3]:
                    if score < .45:
                        continue
                    candidate = {
                        "source": "nexus",
                        "source_key": str(row.get("mod_id") or ""),
                        "url": (
                            f"https://www.nexusmods.com/{nexus_slug}/mods/"
                            f"{row.get('mod_id')}"
                        ),
                        "name": str(row.get("name") or ""),
                        "version": str(row.get("version") or ""),
                        "summary": str(row.get("summary") or "")[:500],
                        "score": score,
                        "detail_verified": False,
                    }
                    try:
                        detail = nexus.get_detail(
                            int(row["mod_id"]), nexus_slug, api_key, cdp_port
                        )
                        candidate.update({
                            "name": str(detail.get("name") or candidate["name"]),
                            "version": str(detail.get("version") or candidate["version"]),
                            "author": str(detail.get("author") or ""),
                            "summary": str(detail.get("summary") or "")[:800],
                            "description": str(detail.get("description") or "")[:2000],
                            "dependencies": detail.get("dependencies") or [],
                            "updated_at": str(detail.get("updated_at") or ""),
                            "detail_verified": True,
                        })
                    except Exception as exc:
                        candidate["detail_error"] = (str(exc) or type(exc).__name__)[:180]
                    candidates.append(candidate)
                report["ambiguous"].append({
                    "mod_id": str(mod.id),
                    "name": mod.name,
                    "current_version": mod.version,
                    "reason": (
                        "发现多个高度相似的 Nexus 项目；名称相似不能证明本机来源，"
                        "必须核对完整详情并由用户确认稳定 ID"
                    ),
                    "candidates": candidates,
                })
                notify(mod, "done")
            else:
                if error:
                    nexus_errors.append(error)
                still_pending.append(mod)
        pending = still_pending
        if cancelled():
            report["cancelled"] = True
            return _finalize_report(report)
        if nexus_errors:
            report["source_errors"].append({
                "source": "nexus",
                "error": f"{len(nexus_errors)} 项查询失败；已保留本地记录，可稍后重试",
            })

    packages = []
    if pending:
        for mod in pending:
            notify(mod, "processing")
        try:
            community = preferred_community or thunderstore.community_hint(
                getattr(cfg, "game_name", "") or "", slug,
            )
            if not community:
                community = thunderstore.find_community(
                    getattr(cfg, "game_name", "") or ""
                )
            report["community"] = community or ""
            if community:
                package_kwargs = {"force_refresh": force_refresh}
                if cancel_check:
                    package_kwargs["cancel_check"] = cancelled
                packages = [
                    _package_row(item)
                    for item in thunderstore.list_packages(community, **package_kwargs)
                ]
            else:
                report["source_errors"].append({
                    "source": "thunderstore",
                    "error": "未能匹配当前游戏的 Thunderstore 社区",
                })
        except Exception as exc:
            if cancelled():
                report["cancelled"] = True
                return _finalize_report(report)
            report["source_errors"].append({
                "source": "thunderstore", "error": str(exc)[:200],
            })

    for mod in pending:
        if cancelled():
            report["cancelled"] = True
            break
        aliases = _local_aliases(mod)
        ranked = sorted(
            ((_score(aliases, package), package) for package in packages),
            key=lambda pair: (pair[0], pair[1].get("downloads", 0)),
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, {})
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        credible = [
            (score, row) for score, row in ranked if score >= .90
        ]
        # Identical package titles can exist under multiple Thunderstore
        # authors. Popularity is not identity evidence, so never auto-pick one.
        exact = best_score == 1.0 and len(credible) == 1
        strong = (
            best_score >= .90
            and best_score - runner_up >= .06
            and len(credible) == 1
        )
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
            notify(mod, "done")
        elif best_score >= .58:
            report["ambiguous"].append(base | {
                "reason": "候选相似，但不足以安全自动绑定",
                "candidates": [
                    _public_candidate(row, score)
                    for score, row in ranked[:3] if score >= .45
                ],
            })
            notify(mod, "done")
        else:
            report["unmatched"].append(base | {
                "reason": (
                    "来源查询失败，未执行名称判定"
                    if report["source_errors"] else
                    "Thunderstore 包清单中没有足够可信的名称匹配"
                ),
            })
            notify(mod, "done")

    return _finalize_report(report)
