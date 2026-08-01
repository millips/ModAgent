"""Portable, privacy-preserving ModAgent configuration shares.

This module deliberately separates a player-created share from the future
official ``ma-xxxxxx`` catalogue.  A share is a reviewable JSON manifest; it
is never an instruction to write files or install a mod without the normal
detail, dependency, and confirmation checks.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse
from urllib.request import Request, urlopen

from . import db, installer, snapshot
from .config import Config, game_storage_id


SCHEMA = "modagent-share/v1"
MAX_SHARE_BYTES = 512 * 1024
_ALLOWED_REMOTE_HOSTS = {"raw.githubusercontent.com", "gist.githubusercontent.com"}
_DEP_VERSION_RE = re.compile(
    r"(?:^|[-_.\s])v?(\d+(?:\.\d+){1,4})(?:[-+][a-z0-9.-]+)?$", re.I,
)


class ShareError(ValueError):
    """A safe, user-actionable share input error."""


def _dependency_identity(value: Any) -> str:
    """Stable identity for package-style dependency labels.

    Thunderstore records dependencies as ``Author-Package-1.2.3`` while an
    exported inventory has a local database id.  Never compare those ids
    directly: use the bound public package key and drop only the version.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = re.sub(r"[-_.\s]+v?\d+(?:\.\d+){1,4}(?:[-+][a-z0-9.-]+)?$", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _dependency_version(value: Any) -> tuple[int, ...]:
    match = _DEP_VERSION_RE.search(str(value or ""))
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def _version_at_least(actual: tuple[int, ...], wanted: tuple[int, ...]) -> bool:
    if not actual or not wanted:
        return True
    width = max(len(actual), len(wanted))
    return tuple((*actual, *([0] * (width - len(actual))))) >= tuple(
        (*wanted, *([0] * (width - len(wanted))))
    )


def _is_base_runtime_dependency(value: Any) -> bool:
    return bool(re.match(r"^(?:bepinex|melonloader|smapi)[-_]", str(value or "").strip(), re.I))


def _base_runtime_evidence(cfg: Config, dependency: str) -> dict[str, Any]:
    """Inspect the selected game directory for a real loader installation.

    Package-manager metadata is not a reliable inventory of BepInEx/SMAPI:
    their bootstrap files deliberately live in the game root and are not normal
    Mod rows.  Treating every such dependency as unresolved made a valid
    collection permanently block its own install-plan button.

    This is intentionally conservative.  It proves the loader *kind* from its
    on-disk runtime files; it does not claim an exact package version when that
    version cannot be read safely from those files.
    """
    configured_root = str(getattr(cfg, "game_root", "") or "").strip()
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(configured_root))) if configured_root else ""
    label = str(dependency or "").casefold()
    if not root or not os.path.isdir(root):
        return {
            "status": "base_environment_not_found",
            "matched_version": "",
            "evidence": [],
            "note": "Selected game directory is unavailable; loader files could not be checked.",
        }

    if label.startswith("bepinex"):
        core = os.path.join(root, "BepInEx", "core")
        candidates = [
            os.path.join(core, "BepInEx.dll"),
            os.path.join(core, "BepInEx.Core.dll"),
        ]
        hits = [os.path.relpath(path, root).replace("\\", "/") for path in candidates if os.path.isfile(path)]
        bootstrap = [
            name for name in ("winhttp.dll", "doorstop_config.ini")
            if os.path.isfile(os.path.join(root, name))
        ]
        if hits:
            return {
                "status": "satisfied_base_environment",
                "matched_version": "runtime files detected",
                "evidence": hits + bootstrap,
                "note": "BepInEx runtime files were found in the selected game directory.",
            }
    elif label.startswith("smapi"):
        candidates = ["StardewModdingAPI.exe", "StardewModdingAPI.dll"]
        hits = [name for name in candidates if os.path.isfile(os.path.join(root, name))]
        if hits:
            return {
                "status": "satisfied_base_environment",
                "matched_version": "runtime files detected",
                "evidence": hits,
                "note": "SMAPI runtime files were found in the selected game directory.",
            }
    elif label.startswith("melonloader"):
        candidates = ["MelonLoader", "version.dll"]
        hits = [name for name in candidates if os.path.exists(os.path.join(root, name))]
        if hits:
            return {
                "status": "satisfied_base_environment",
                "matched_version": "runtime files detected",
                "evidence": hits,
                "note": "MelonLoader runtime files were found in the selected game directory.",
            }
    return {
        "status": "base_environment_not_found",
        "matched_version": "",
        "evidence": [],
        "note": "Required base runtime files were not found in the selected game directory.",
    }


def _source_identity(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return _dependency_identity(source.get("key")) or _dependency_identity(item.get("name"))


def _share_dependency_requirements(payload: dict, cfg: Config, scope: str) -> list[dict]:
    """Classify prerequisites without pretending external runtimes are Mods.

    A reviewed collection can include a package prerequisite itself, reference
    an already installed package, or require a base runtime/external package.
    The latter are deliberately carried to the recipient's preflight step.
    """
    mods = [item for item in payload.get("mods", []) if isinstance(item, dict)]
    local_ids = {str(item.get("local_id") or "").strip() for item in mods}
    collection_packages = {
        _source_identity(item): item for item in mods if _source_identity(item)
    }
    bindings = {
        str(item.get("mod_id") or ""): item
        for item in db.get_mod_source_bindings(scope)
        if isinstance(item, dict)
    }
    installed_packages: dict[str, str] = {}
    for installed in db.get_installed_mods(scope):
        binding = bindings.get(str(installed.id), {})
        identity = _dependency_identity(binding.get("source_key")) or _dependency_identity(installed.name)
        if identity:
            installed_packages[identity] = str(installed.version or binding.get("latest_version") or "")

    requirements: dict[str, dict] = {}
    for mod in mods:
        for raw in mod.get("dependencies") or []:
            label = str(raw or "").strip()
            identity = _dependency_identity(label)
            if not label or not identity:
                continue
            entry = requirements.setdefault(identity, {
                "id": identity,
                "name": label,
                "required_by": [],
                "requested_version": _dependency_version(label),
            })
            version = _dependency_version(label)
            if version > entry["requested_version"]:
                entry["name"], entry["requested_version"] = label, version
            mod_name = str(mod.get("localized_name") or mod.get("name") or "未命名 Mod")
            if mod_name not in entry["required_by"]:
                entry["required_by"].append(mod_name)

    for identity, entry in requirements.items():
        wanted = entry.pop("requested_version")
        included = collection_packages.get(identity)
        if included:
            actual_label = str((included.get("source") or {}).get("version") or included.get("version") or "")
            entry.update({
                "status": "included_collection" if _version_at_least(_dependency_version(actual_label), wanted) else "collection_version_review",
                "scope": "collection",
                "matched_mod": str(included.get("localized_name") or included.get("name") or ""),
                "matched_version": actual_label,
            })
        elif _is_base_runtime_dependency(entry["name"]):
            evidence = _base_runtime_evidence(cfg, entry["name"])
            entry.update({
                "status": evidence["status"],
                "scope": "base_environment",
                "matched_mod": "",
                "matched_version": evidence["matched_version"],
                "evidence": evidence["evidence"],
                "note": evidence["note"],
            })
        elif identity in installed_packages and _version_at_least(_dependency_version(installed_packages[identity]), wanted):
            entry.update({
                "status": "satisfied_installed",
                "scope": "installed",
                "matched_mod": "本机已安装",
                "matched_version": installed_packages[identity],
            })
        else:
            entry.update({
                "status": "needs_external_resolution",
                "scope": "external",
                "matched_mod": "",
                "matched_version": "",
            })
        entry["requested_version"] = ".".join(map(str, wanted))
    return sorted(requirements.values(), key=lambda item: (item["scope"], item["name"].casefold()))


def _as_files(value: Any) -> list[str]:
    try:
        files = json.loads(value) if isinstance(value, str) else (value or [])
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in files] if isinstance(files, list) else []


def _enabled(mod: db.InstalledMod) -> bool:
    try:
        return not installer.is_mod_disabled(_as_files(mod.files_installed))
    except Exception:
        # A share must still be exportable if an old inventory row is malformed.
        return True


def _binding_public_view(binding: dict | None) -> dict:
    binding = binding or {}
    # Do not pass on binding metadata: it may contain cache/debug details that
    # are neither stable nor useful to another player's installation.
    return {
        "type": str(binding.get("source") or "").strip(),
        "key": str(binding.get("source_key") or "").strip(),
        "url": str(binding.get("source_url") or "").strip(),
        "version": str(binding.get("latest_version") or "").strip(),
        "confidence": str(binding.get("confidence") or "").strip(),
    }


def build_share_payload(
    cfg: Config,
    *,
    author_note: str = "",
    title: str = "",
    description: str = "",
    warning: str = "",
    author_name: str = "",
    source_evidence: str = "",
    compatibility: str = "",
    selected_mod_ids: list[str] | None = None,
    require_verified_sources: bool = False,
    include_snapshots: bool = False,
    include_config_metadata: bool = False,
) -> dict:
    """Export the current game's inventory without paths, keys, or file data."""
    scope = game_storage_id(cfg, cfg.game_slug)
    selected_ids = {str(item).strip() for item in (selected_mod_ids or []) if str(item).strip()}
    bindings = {str(item["mod_id"]): item for item in db.get_mod_source_bindings(scope)}
    notes = db.get_mod_catalog_notes(scope)
    mods: list[dict] = []
    unverified: list[str] = []
    for mod in db.get_installed_mods(scope):
        if selected_ids and str(mod.id) not in selected_ids:
            continue
        note = notes.get(str(mod.id), {})
        source = _binding_public_view(bindings.get(str(mod.id)))
        warnings = []
        if not source["type"] or not source["url"]:
            warnings.append("source_unbound: recipient must choose and verify a source")
            unverified.append(str(mod.name))
        mods.append({
            "local_id": str(mod.id),
            "name": str(mod.name),
            "localized_name": str(note.get("localized_name") or ""),
            "summary": str(note.get("summary") or ""),
            "version": str(mod.version or ""),
            "enabled": _enabled(mod),
            "load_order": int(mod.load_order or 0),
            "dependencies": db.parse_dependencies(mod.dependencies),
            "source": source,
            "warnings": warnings,
        })

    missing_selected = selected_ids - {str(item["local_id"]) for item in mods}
    if missing_selected:
        raise ShareError("Some selected Mods are no longer in the current game's inventory. Refresh the Mod list and try again.")
    if require_verified_sources and unverified:
        raise ShareError(
            "Every selected Mod must have a verified source before it can be submitted: "
            + ", ".join(unverified[:8])
        )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "player_share",
        "created_at": int(time.time()),
        "title": str(title or "").strip()[:100],
        "description": str(description or "").strip()[:2000],
        "warning": str(warning or "").strip()[:2000],
        "author": {"display_name": str(author_name or "").strip()[:80]},
        "submission": {
            "id": f"ms-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
            "state": "draft",
        },
        "author_note": str(author_note or "").strip()[:2000],
        # Kept separately so an official catalogue can show concise review
        # metadata without having to parse an unstructured author note.
        "source_evidence": str(source_evidence or "").strip()[:5000],
        "compatibility": str(compatibility or "").strip()[:3000],
        "game": {
            "name": str(cfg.game_name or ""),
            "slug": str(cfg.game_slug or ""),
            "mod_loader": str(cfg.mod_loader or ""),
        },
        "mods": mods,
        # Reserved for Phase 2 official collections such as ma-263484.
        "share_id": "",
        "configuration": {
            "included": False,
            "metadata_requested": bool(include_config_metadata),
            "note": "Config file contents are never exported automatically.",
        },
        "snapshots": {"included": False, "items": []},
        "privacy": {
            "game_paths_included": False,
            "api_keys_included": False,
            "installed_file_paths_included": False,
        },
    }
    if include_snapshots:
        payload["snapshots"] = {
            "included": True,
            "items": [
                {
                    "id": item.id,
                    "timestamp": item.timestamp,
                    "trigger_mod_name": item.trigger_mod_name,
                    "files_count": len(_as_files(item.files)),
                    "available": bool(snapshot.find_snapshot_dir(item.id, scope)),
                }
                for item in db.list_snapshots(scope)
            ],
        }
    return payload


def serialize_share(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def make_offline_share_link(payload: dict) -> str:
    raw = serialize_share(payload).encode("utf-8")
    return "data:application/vnd.modagent-share+json;base64," + base64.b64encode(raw).decode("ascii")


def _read_data_uri(value: str) -> str:
    header, separator, body = value.partition(",")
    if not separator or not header.lower().startswith("data:"):
        raise ShareError("Invalid offline share link.")
    try:
        data = base64.b64decode(body, validate=True) if ";base64" in header.lower() else unquote_to_bytes(body)
    except Exception as exc:
        raise ShareError("Offline share link is malformed.") from exc
    if len(data) > MAX_SHARE_BYTES:
        raise ShareError("Share is too large (maximum 512 KiB).")
    return data.decode("utf-8")


def _read_remote_share(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_REMOTE_HOSTS:
        raise ShareError("Only HTTPS GitHub Raw or Gist Raw links are accepted.")
    request = Request(value, headers={"User-Agent": "ModAgent/1.5 share importer"})
    try:
        with urlopen(request, timeout=12) as response:
            data = response.read(MAX_SHARE_BYTES + 1)
    except Exception as exc:
        raise ShareError(f"Could not fetch the shared manifest: {exc}") from exc
    if len(data) > MAX_SHARE_BYTES:
        raise ShareError("Share is too large (maximum 512 KiB).")
    return data.decode("utf-8")


def read_allowed_remote_url(value: str) -> str:
    """Fetch a small JSON document from an approved GitHub Raw/Gist host."""
    return _read_remote_share(str(value or "").strip())


def load_share_input(value: str) -> tuple[dict, str]:
    value = str(value or "").strip()
    if not value:
        raise ShareError("Paste a JSON manifest, offline share link, GitHub Raw link, or Gist Raw link.")
    if value.startswith("data:"):
        raw, source = _read_data_uri(value), "offline_link"
    elif value.startswith("https://"):
        raw, source = _read_remote_share(value), "github_raw"
    else:
        raw, source = value, "pasted_json"
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ShareError("The share is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ShareError("The share root must be a JSON object.")
    validate_share_payload(payload)
    return payload, source


def validate_share_payload(payload: dict) -> None:
    if payload.get("schema") != SCHEMA:
        raise ShareError("Unsupported share schema. Expected modagent-share/v1.")
    if payload.get("kind") not in {"player_share", "official_collection"}:
        raise ShareError("Unsupported share kind.")
    if not isinstance(payload.get("game"), dict):
        raise ShareError("Share is missing game metadata.")
    mods = payload.get("mods")
    if not isinstance(mods, list) or len(mods) > 500:
        raise ShareError("Share must contain 0–500 mod entries.")
    for index, item in enumerate(mods, 1):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ShareError(f"Mod entry {index} is missing a name.")
        if not isinstance(item.get("source") or {}, dict):
            raise ShareError(f"Mod entry {index} has invalid source data.")


def inspect_share_import(payload: dict, cfg: Config) -> dict:
    """Return a non-mutating review/verification plan for an imported share."""
    validate_share_payload(payload)
    scope = game_storage_id(cfg, cfg.game_slug)
    items = []
    local_ids = {str(item.get("local_id") or "") for item in payload["mods"]}
    for item in payload["mods"]:
        source = item.get("source") or {}
        source_type = str(source.get("type") or "").strip()
        source_key = str(source.get("key") or "").strip()
        installed = db.get_mod_by_source(scope, source_type, source_key) if source_type and source_key else None
        dependencies = [str(dep) for dep in (item.get("dependencies") or []) if str(dep).strip()]
        if installed:
            status = "already_installed"
        elif source_type and (source_key or str(source.get("url") or "").strip()):
            status = "ready_for_source_verification"
        else:
            status = "needs_source_resolution"
        items.append({
            "name": str(item.get("name") or ""),
            "localized_name": str(item.get("localized_name") or ""),
            "version": str(item.get("version") or ""),
            "enabled": bool(item.get("enabled", True)),
            "load_order": item.get("load_order", 0),
            "source": _binding_public_view(source),
            "dependencies": dependencies,
            "status": status,
            "installed_match": {
                "id": str(installed.id), "name": installed.name, "version": installed.version,
            } if installed else None,
            "warnings": list(item.get("warnings") or []),
        })
    installed_count = sum(1 for item in items if item["status"] == "already_installed")
    dependency_requirements = _share_dependency_requirements(payload, cfg, scope)
    host_requirements = [
        item for item in dependency_requirements
        if item.get("scope") == "base_environment"
        or item.get("status") in {"needs_external_resolution", "collection_version_review"}
    ]
    return {
        "kind": "share_import_preview",
        "schema": SCHEMA,
        "source_kind": "player_share",
        "game": payload.get("game", {}),
        "author_note": str(payload.get("author_note") or ""),
        "items": items,
        "summary": {
            "total": len(items),
            "already_installed": installed_count,
            "needs_verification": sum(1 for item in items if item["status"] == "ready_for_source_verification"),
            "needs_source_resolution": sum(1 for item in items if item["status"] == "needs_source_resolution"),
            "dependency_requirements": dependency_requirements,
            "host_dependency_requirements": host_requirements,
        },
        "safe_to_auto_install": False,
        "next_step": "Review the preview, then verify sources, local dependencies, base runtime and conflicts before creating the normal installation plan. Base runtimes and external prerequisites are checked on the recipient's machine; they are not silently treated as collection Mods. Nothing has been installed or changed.",
    }
