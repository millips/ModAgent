"""Read-only official ModAgent collection catalogue.

Official collections remain reviewed JSON in the public GitHub repository.  The
client deliberately uses more than one GitHub endpoint and keeps the last
verified catalogue locally: some networks can open github.com but reset the
raw.githubusercontent.com connection.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .config import CONFIG_DIR, Config
from . import share_config


INDEX_SCHEMA = "modagent-official-share-index/v1"
CACHE_SCHEMA = "modagent-official-share-cache/v1"
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/millips/ModAgent-Share/main/index.json"
_CODE_RE = re.compile(r"^ma-[a-z0-9][a-z0-9_-]{1,47}-\d{6}$", re.IGNORECASE)
_MAX_REMOTE_BYTES = 1024 * 1024


class OfficialShareError(ValueError):
    pass


def _cache_file() -> Path:
    return Path(CONFIG_DIR) / "official-share-cache.json"


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
        # The index always records a Raw URL.  The GitHub Contents API below is
        # only a transport fallback derived from that exact reviewed URL.
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


def _contents_api_url(raw_url: str) -> str:
    """Map one reviewed Raw GitHub URL to its equivalent Contents API URL."""
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4:
        return ""
    owner, repo, ref = parts[:3]
    path = "/".join(parts[3:])
    return (
        f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents/"
        f"{quote(path, safe='/')}?ref={quote(ref)}"
    )


def _read_github_contents_api(url: str) -> str:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ModAgent/1.6 official-collections",
    })
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(_MAX_REMOTE_BYTES + 1)
    except Exception as exc:
        raise OfficialShareError(f"GitHub Contents API unavailable: {exc}") from exc
    if len(raw) > _MAX_REMOTE_BYTES:
        raise OfficialShareError("GitHub Contents API response is too large.")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise ValueError("missing base64 content")
        # GitHub's Contents API wraps the base64 body with line breaks.  Keep
        # strict validation, but remove that transport formatting first.
        encoded = "".join(payload["content"].split())
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialShareError("GitHub Contents API returned an invalid file payload.") from exc


def _read_github_blob_page(url: str) -> str:
    """Read the reviewed file from github.com itself as a last GitHub route.

    This is deliberately *not* an HTML scraper.  GitHub renders the raw file
    from its normal repository domain when ``?raw=1`` is present, which helps
    networks that reset raw.githubusercontent.com while allowing github.com.
    The URL is derived only from the already reviewed Raw location.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise OfficialShareError("GitHub web fallback requires a reviewed Raw URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4:
        raise OfficialShareError("Reviewed Raw URL has no repository path.")
    owner, repo, ref = parts[:3]
    path = "/".join(parts[3:])
    page_url = (
        f"https://github.com/{quote(owner)}/{quote(repo)}/raw/"
        f"{quote(ref)}/{quote(path, safe='/')}"
    )
    request = Request(page_url, headers={"User-Agent": "ModAgent/1.6 official-collections"})
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(_MAX_REMOTE_BYTES + 1)
    except Exception as exc:
        raise OfficialShareError(f"GitHub web file endpoint unavailable: {exc}") from exc
    if len(raw) > _MAX_REMOTE_BYTES:
        raise OfficialShareError("GitHub web file endpoint response is too large.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OfficialShareError("GitHub web file endpoint returned non-text content.") from exc


def _read_remote_candidates(raw_url: str) -> tuple[str, str, list[str]]:
    """Fetch from Raw first, then the API endpoint for the same reviewed file."""
    errors: list[str] = []
    try:
        return share_config.read_allowed_remote_url(raw_url), "github_raw", errors
    except share_config.ShareError as exc:
        errors.append(f"GitHub Raw: {exc}")
    api_url = _contents_api_url(raw_url)
    if api_url:
        try:
            return _read_github_contents_api(api_url), "github_contents_api", errors
        except OfficialShareError as exc:
            errors.append(f"GitHub API: {exc}")
    try:
        return _read_github_blob_page(raw_url), "github_web_raw", errors
    except OfficialShareError as exc:
        errors.append(f"GitHub web: {exc}")
    raise OfficialShareError("; ".join(errors) or "No approved GitHub endpoint is available.")


def _read_cache() -> dict:
    try:
        payload = json.loads(_cache_file().read_text(encoding="utf-8"))
        if payload.get("schema") != CACHE_SCHEMA:
            return {}
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _write_cache(payload: dict) -> None:
    """Best-effort cache only; a cache write must never block an import."""
    try:
        target = _cache_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(target)
    except OSError:
        pass


def _cache_index(url: str, payload: dict) -> None:
    cache = _read_cache()
    cache.update({
        "schema": CACHE_SCHEMA,
        "index": {"url": url, "payload": payload, "saved_at": time.time()},
        "manifests": cache.get("manifests") if isinstance(cache.get("manifests"), dict) else {},
    })
    _write_cache(cache)


def _cached_index(url: str) -> tuple[dict, float] | None:
    cached = _read_cache().get("index")
    if not isinstance(cached, dict) or str(cached.get("url") or "") != url:
        return None
    payload = cached.get("payload")
    try:
        validate_index(payload)
    except OfficialShareError:
        return None
    return payload, float(cached.get("saved_at") or 0)


def _cache_manifest(code: str, raw_url: str, payload: dict) -> None:
    cache = _read_cache()
    manifests = cache.get("manifests") if isinstance(cache.get("manifests"), dict) else {}
    manifests[str(code).lower()] = {"url": raw_url, "payload": payload, "saved_at": time.time()}
    cache.update({"schema": CACHE_SCHEMA, "manifests": manifests})
    _write_cache(cache)


def _cached_manifest(code: str, raw_url: str) -> tuple[dict, float] | None:
    item = (_read_cache().get("manifests") or {}).get(str(code).lower())
    if not isinstance(item, dict) or str(item.get("url") or "") != raw_url:
        return None
    payload = item.get("payload")
    return (payload, float(item.get("saved_at") or 0)) if isinstance(payload, dict) else None


def _age_seconds(saved_at: float) -> int | None:
    return max(0, int(time.time() - saved_at)) if saved_at else None


def _catalog_payload(cfg: Config) -> tuple[dict, str, bool, str, int | None]:
    url = str(getattr(cfg, "official_share_index_url", "") or DEFAULT_INDEX_URL).strip()
    try:
        raw, source, errors = _read_remote_candidates(url)
        payload = json.loads(raw)
        validate_index(payload)
        _cache_index(url, payload)
        return payload, source, True, "; ".join(errors), None
    except (OfficialShareError, ValueError, TypeError, json.JSONDecodeError) as exc:
        cached = _cached_index(url)
        if cached:
            payload, saved_at = cached
            return payload, "local_cache", False, str(exc), _age_seconds(saved_at)
        bundled = _bundled_index()
        return bundled, "bundled_fallback", False, str(exc), None


def load_catalog(cfg: Config, query: str = "", game_slug: str | None = None) -> dict:
    url = str(getattr(cfg, "official_share_index_url", "") or DEFAULT_INDEX_URL).strip()
    payload, source, fetched, fetch_error, cache_age_seconds = _catalog_payload(cfg)
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
    available = bool(payload.get("collections"))
    return {
        "kind": "official_share_catalog",
        "schema": INDEX_SCHEMA,
        "source": source,
        "fetched": fetched,
        "available": available,
        "cache_age_seconds": cache_age_seconds,
        "index_url": url,
        "collections": results[:100],
        "total": len(results),
        "fetch_error": fetch_error,
        "note": (
            "Official collections are reviewed manifests hosted on GitHub. "
            "Selecting one only opens a verification preview; it never installs automatically."
        ),
    }


def _load_manifest(code: str, entry: dict) -> tuple[dict, str, int | None]:
    raw_url = str(entry.get("manifest_url") or "")
    try:
        raw, source, _errors = _read_remote_candidates(raw_url)
        payload = json.loads(raw)
        share_config.validate_share_payload(payload)
        _cache_manifest(code, raw_url, payload)
        return payload, source, None
    except (OfficialShareError, share_config.ShareError, ValueError, TypeError, json.JSONDecodeError) as exc:
        cached = _cached_manifest(code, raw_url)
        if cached:
            payload, saved_at = cached
            try:
                share_config.validate_share_payload(payload)
                return payload, "local_cache", _age_seconds(saved_at)
            except share_config.ShareError:
                pass
        raise OfficialShareError(f"Could not fetch reviewed manifest {code}: {exc}") from exc


def load_official_collection(cfg: Config, share_id: str) -> tuple[dict, dict]:
    code = str(share_id or "").strip().lower()
    if not _CODE_RE.fullmatch(code):
        raise OfficialShareError("Official collection code must look like ma-repo-000001.")
    catalog = load_catalog(cfg, game_slug="")
    if not catalog["available"]:
        raise OfficialShareError(
            "Could not reach the official collection index and no verified local cache is available; no local installation was changed."
        )
    entry = next((item for item in catalog["collections"] if item["id"] == code), None)
    if not entry:
        raise OfficialShareError(f"Official collection {code} was not found.")
    selected_game = str(getattr(cfg, "game_slug", "") or "").casefold()
    if selected_game and str(entry.get("game_slug") or "").casefold() != selected_game:
        raise OfficialShareError(f"{code} belongs to {entry['game_slug']}, not the currently selected game.")
    payload, manifest_source, manifest_cache_age = _load_manifest(code, entry)
    if payload.get("kind") != "official_collection" or str(payload.get("share_id") or "").lower() != code:
        raise OfficialShareError(f"Reviewed manifest {code} failed identity validation.")
    if str(payload.get("game", {}).get("slug") or "").casefold() != str(entry.get("game_slug") or "").casefold():
        raise OfficialShareError(f"Reviewed manifest {code} failed game validation.")
    entry = dict(entry)
    entry.update({
        "catalog_source": catalog["source"],
        "catalog_cache_age_seconds": catalog.get("cache_age_seconds"),
        "manifest_source": manifest_source,
        "manifest_cache_age_seconds": manifest_cache_age,
    })
    return payload, entry


def connectivity_diagnostics(cfg: Config) -> dict:
    """Read-only health data for support; it never changes config or installs."""
    url = str(getattr(cfg, "official_share_index_url", "") or DEFAULT_INDEX_URL).strip()
    checks = []
    for label, candidate in (
        ("github_raw", url),
        ("github_contents_api", _contents_api_url(url)),
        ("github_web_raw", url),
    ):
        if not candidate:
            continue
        try:
            if label == "github_raw":
                raw = share_config.read_allowed_remote_url(candidate)
            elif label == "github_contents_api":
                raw = _read_github_contents_api(candidate)
            else:
                raw = _read_github_blob_page(candidate)
            payload = json.loads(raw)
            validate_index(payload)
            checks.append({"endpoint": label, "ok": True, "collections": len(payload["collections"])})
        except Exception as exc:
            checks.append({"endpoint": label, "ok": False, "error": str(exc)[:300]})
    return {
        "kind": "official_share_network_diagnostics",
        "checks": checks,
        "cache_available": _cached_index(url) is not None,
        "note": "Checks only the reviewed official collection endpoints; no local installation or credentials are changed.",
    }


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
