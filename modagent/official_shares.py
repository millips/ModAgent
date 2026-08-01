"""Read-only official ModAgent collection catalogue.

Official collections are deliberately hosted as reviewed JSON in the public
source repository.  This keeps moderation/version history on GitHub and does
not introduce a service, account system, or private API into the client.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import Config
from . import share_config


INDEX_SCHEMA = "modagent-official-share-index/v1"
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/millips/ModAgent-Share/main/index.json"
_CODE_RE = re.compile(r"^ma-[a-z0-9][a-z0-9_-]{1,47}-\d{6}$", re.IGNORECASE)


class OfficialShareError(ValueError):
    pass


def _bundled_index() -> dict:
    # PyInstaller places ``datas`` under _MEIPASS; source/dev mode keeps the
    # same folder at the repository root.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = base / "shares" / "index.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_index(payload)
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"schema": INDEX_SCHEMA, "collections": []}


def validate_index(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != INDEX_SCHEMA:
        raise OfficialShareError("Unsupported official collection index.")
    collections = payload.get("collections")
    if not isinstance(collections, list) or len(collections) > 500:
        raise OfficialShareError("Official collection index has invalid collection entries.")
    codes: set[str] = set()
    for position, entry in enumerate(collections, 1):
        if not isinstance(entry, dict):
            raise OfficialShareError(f"Official collection {position} is invalid.")
        code = str(entry.get("id") or "").strip().lower()
        if not _CODE_RE.fullmatch(code) or code in codes:
            raise OfficialShareError(f"Official collection {position} has an invalid or duplicate code.")
        codes.add(code)
        url = str(entry.get("manifest_url") or "").strip()
        if not url:
            raise OfficialShareError(f"Official collection {code} has no reviewed manifest URL.")
        # Reuse the same restrictive host policy as player shares.  Merely
        # loading here validates the host; it is not downloaded yet.
        if not url.startswith("https://raw.githubusercontent.com/"):
            raise OfficialShareError(f"Official collection {code} has an unsafe manifest URL.")


def _public_entry(entry: dict) -> dict:
    return {
        "id": str(entry.get("id") or "").lower(),
        "game_slug": str(entry.get("game_slug") or ""),
        "game_name": str(entry.get("game_name") or ""),
        "mod_loader": str(entry.get("mod_loader") or ""),
        "title": str(entry.get("title") or ""),
        "description": str(entry.get("description") or ""),
        "author_display_name": str(entry.get("author_display_name") or ""),
        "tags": [str(tag) for tag in (entry.get("tags") or [])][:12],
        "warnings": [str(item) for item in (entry.get("warnings") or [])][:12],
        "compatibility": str(entry.get("compatibility") or "")[:3000],
        "source_types": [str(item) for item in (entry.get("source_types") or [])][:12],
        "source_hosts": [str(item) for item in (entry.get("source_hosts") or [])][:24],
        "mod_count": max(0, int(entry.get("mod_count") or 0)),
        "dependency_count": max(0, int(entry.get("dependency_count") or 0)),
        "reviewed_at": str(entry.get("reviewed_at") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
        "manifest_url": str(entry.get("manifest_url") or ""),
    }


def load_catalog(cfg: Config, query: str = "", game_slug: str | None = None) -> dict:
    url = str(getattr(cfg, "official_share_index_url", "") or DEFAULT_INDEX_URL).strip()
    source, fetched = "remote", True
    try:
        raw = share_config.read_allowed_remote_url(url)
        payload = json.loads(raw)
        validate_index(payload)
    except (share_config.ShareError, ValueError, TypeError, json.JSONDecodeError) as exc:
        payload = _bundled_index()
        source, fetched = "bundled_fallback", False
        fetch_error = str(exc)
    else:
        fetch_error = ""

    needle = str(query or "").strip().casefold()
    selected_game = str(cfg.game_slug if game_slug is None else game_slug or "").strip().casefold()
    results = []
    for entry in payload["collections"]:
        public = _public_entry(entry)
        haystack = " ".join([
            public["id"], public["game_slug"], public["game_name"], public["title"],
            public["description"], *public["tags"],
        ]).casefold()
        if selected_game and public["game_slug"].casefold() != selected_game:
            continue
        if needle and needle not in haystack:
            continue
        results.append(public)
    return {
        "kind": "official_share_catalog",
        "schema": INDEX_SCHEMA,
        "source": source,
        "fetched": fetched,
        "index_url": url,
        "collections": results[:100],
        "total": len(results),
        "fetch_error": fetch_error,
        "note": (
            "Official collections are reviewed manifests hosted on GitHub. "
            "Selecting one only opens a verification preview; it never installs automatically."
        ),
    }


def load_official_collection(cfg: Config, share_id: str) -> tuple[dict, dict]:
    code = str(share_id or "").strip().lower()
    if not _CODE_RE.fullmatch(code):
        raise OfficialShareError("Official collection code must look like ma-repo-000001.")
    catalog = load_catalog(cfg)
    if not catalog["fetched"]:
        raise OfficialShareError(
            "Could not reach the official collection index. Check network access and try again; no local installation was changed."
        )
    entry = next((item for item in catalog["collections"] if item["id"] == code), None)
    if not entry:
        # Catalog is filtered by current game, so search the unfiltered index
        # once for a useful wrong-game answer.
        all_catalog = load_catalog(cfg, game_slug="")
        candidate = next((item for item in all_catalog["collections"] if item["id"] == code), None)
        if candidate and candidate.get("game_slug"):
            raise OfficialShareError(
                f"{code} belongs to {candidate['game_slug']}, not the currently selected game."
            )
        raise OfficialShareError(f"Official collection {code} was not found.")
    try:
        payload, _ = share_config.load_share_input(entry["manifest_url"])
    except share_config.ShareError as exc:
        raise OfficialShareError(f"Could not fetch reviewed manifest {code}: {exc}") from exc
    if payload.get("kind") != "official_collection" or str(payload.get("share_id") or "").lower() != code:
        raise OfficialShareError(f"Reviewed manifest {code} failed identity validation.")
    if str(payload.get("game", {}).get("slug") or "").casefold() != str(entry.get("game_slug") or "").casefold():
        raise OfficialShareError(f"Reviewed manifest {code} failed game validation.")
    return payload, entry


def inspect_official_collection(cfg: Config, share_id: str) -> dict:
    payload, entry = load_official_collection(cfg, share_id)
    preview = share_config.inspect_share_import(payload, cfg)
    preview.update({
        "kind": "official_share_import_preview",
        "source_kind": "official_collection",
        "official": entry,
        "next_step": (
            "Review this official collection, then use the normal installation plan. "
            "Sources, dependencies, conflicts, loader compatibility, and local duplicates still require verification."
        ),
    })
    return preview
