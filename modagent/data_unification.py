"""Safe, explicit unification of legacy Beta and stable ModAgent data.

The migration never deletes the legacy directory.  It creates database/config
backups, merges durable records into the canonical data directory, and records
the legacy snapshot directory as an additional read-only lookup root.  This is
deliberately separate from normal startup: a channel switch must never silently
rewrite a user's history.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path


TABLES = (
    "sessions", "installed_mods", "snapshots", "mod_source_bindings",
    "mod_catalog_notes", "custom_domains",
)
MIGRATION_STATE_FILE = "legacy-beta-unification.json"


def _json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def inspect(canonical_root: str, legacy_root: str) -> dict:
    canonical = Path(canonical_root).expanduser().resolve()
    legacy = Path(legacy_root).expanduser().resolve()
    result = {"canonical": str(canonical), "legacy": str(legacy), "available": False}
    db_path = legacy / "state.db"
    if not db_path.is_file():
        return result
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        counts = {}
        for table in TABLES + ("operation_log",):
            try:
                counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.DatabaseError:
                counts[table] = 0
        result.update({
            "available": True,
            "counts": counts,
            "snapshot_root": str(legacy / "snapshots"),
            "snapshot_root_exists": (legacy / "snapshots").is_dir(),
        })
        return result
    finally:
        con.close()


def _merge_config(canonical: Path, legacy: Path) -> None:
    target_path, source_path = canonical / "config.json", legacy / "config.json"
    target, source = _json(target_path), _json(source_path)
    # Stable/current scalar settings win.  Only append independent registry
    # structures so an API key or a newer selected game is never overwritten.
    existing_games = list(target.get("manual_games") or [])
    seen_games = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in existing_games}
    for item in source.get("manual_games") or []:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen_games:
            existing_games.append(item)
            seen_games.add(key)
    if existing_games:
        target["manual_games"] = existing_games
    roots = dict(target.get("manual_mod_dirs") or {})
    for game, dirs in (source.get("manual_mod_dirs") or {}).items():
        combined = list(roots.get(game) or [])
        for directory in dirs or []:
            if directory not in combined:
                combined.append(directory)
        roots[game] = combined
    if roots:
        target["manual_mod_dirs"] = roots
    if target:
        with target_path.open("w", encoding="utf-8") as handle:
            json.dump(target, handle, ensure_ascii=False, indent=2)


def _copy_backup(source: Path, destination: Path, label: str) -> None:
    if source.is_file():
        shutil.copy2(source, destination / f"{label}-{source.name}")


def _upsert_latest(dest: sqlite3.Connection, source: sqlite3.Connection, table: str, keys: tuple[str, ...], stamp: str) -> int:
    columns = [item[1] for item in dest.execute(f"PRAGMA table_info({table})")]
    if not columns:
        return 0
    quoted = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    where = " AND ".join(f"{key}=?" for key in keys)
    changed = 0
    for row in source.execute(f"SELECT {quoted} FROM {table}"):
        values = tuple(row)
        key_values = tuple(values[columns.index(key)] for key in keys)
        current = dest.execute(f"SELECT {stamp} FROM {table} WHERE {where}", key_values).fetchone()
        incoming = values[columns.index(stamp)] or 0
        if current is None:
            dest.execute(f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})", values)
            changed += 1
        elif incoming > (current[0] or 0):
            assignments = ", ".join(f"{name}=?" for name in columns)
            dest.execute(f"UPDATE {table} SET {assignments} WHERE {where}", values + key_values)
            changed += 1
    return changed


def merge(canonical_root: str, legacy_root: str) -> dict:
    canonical = Path(canonical_root).expanduser().resolve()
    legacy = Path(legacy_root).expanduser().resolve()
    canonical_db, legacy_db = canonical / "state.db", legacy / "state.db"
    if not canonical_db.is_file() or not legacy_db.is_file():
        raise FileNotFoundError("Both canonical and legacy state.db files are required")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = canonical / "migration-backups" / f"beta-unification-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for root, label in ((canonical, "canonical"), (legacy, "legacy")):
        _copy_backup(root / "state.db", backup, label)
        _copy_backup(root / "config.json", backup, label)
    dest = sqlite3.connect(canonical_db)
    source = sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True)
    merged = {}
    try:
        dest.execute("BEGIN IMMEDIATE")
        merged["sessions"] = _upsert_latest(dest, source, "sessions", ("id",), "updated_at")
        merged["installed_mods"] = _upsert_latest(dest, source, "installed_mods", ("game_slug", "id"), "installed_at")
        merged["snapshots"] = _upsert_latest(dest, source, "snapshots", ("id",), "timestamp")
        merged["mod_source_bindings"] = _upsert_latest(dest, source, "mod_source_bindings", ("game_slug", "mod_id"), "last_checked_at")
        merged["mod_catalog_notes"] = _upsert_latest(dest, source, "mod_catalog_notes", ("game_slug", "mod_id"), "updated_at")
        for game_slug, path, added_at in source.execute("SELECT game_slug,path,added_at FROM custom_domains"):
            dest.execute("INSERT OR IGNORE INTO custom_domains(game_slug,path,added_at) VALUES (?,?,?)", (game_slug, path, added_at))
        known_log = {(row[0], row[1], row[2]) for row in dest.execute("SELECT timestamp,action,details FROM operation_log")}
        log_added = 0
        for row in source.execute("SELECT timestamp,action,details FROM operation_log"):
            if tuple(row) not in known_log:
                dest.execute("INSERT INTO operation_log(timestamp,action,details) VALUES (?,?,?)", tuple(row))
                log_added += 1
        merged["operation_log"] = log_added
        dest.commit()
    except Exception:
        dest.rollback()
        raise
    finally:
        source.close()
        dest.close()
    _merge_config(canonical, legacy)
    roots_file = canonical / "legacy-snapshot-roots.json"
    roots_data = _json(roots_file)
    roots = list(roots_data.get("roots") or [])
    legacy_snapshots = str(legacy / "snapshots")
    if os.path.isdir(legacy_snapshots) and legacy_snapshots not in roots:
        roots.append(legacy_snapshots)
    with roots_file.open("w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "roots": roots, "updated_at": time.time()}, handle, ensure_ascii=False, indent=2)
    return {"backup": str(backup), "merged": merged, "legacy_snapshot_root": legacy_snapshots}


def migrate_default_beta_history(canonical_root: str) -> dict:
    """Idempotently merge the old ``.modagent-beta`` profile on startup.

    Pre-1.5.2 Beta builds used a second backend data directory.  That was a
    channel mistake, not a user profile boundary.  When an updated build first
    starts, migrate it once; if the user subsequently starts an old Beta build
    again, its changed database fingerprint triggers one more safe merge.
    ``merge`` is non-destructive and creates a backup before every real pass.
    """
    canonical = Path(canonical_root).expanduser().resolve()
    # Do not touch user-selected/smoke-test data roots.  Only the historical
    # default directory has a well-defined legacy sibling.
    if canonical.name.lower() != ".modagent":
        return {"status": "not_default_data_root"}
    legacy = canonical.parent / ".modagent-beta"
    legacy_db = legacy / "state.db"
    if not legacy_db.is_file() or legacy.resolve() == canonical:
        return {"status": "no_legacy_beta"}
    stat = legacy_db.stat()
    fingerprint = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    state_path = canonical / MIGRATION_STATE_FILE
    previous = _json(state_path)
    if previous.get("legacy_fingerprint") == fingerprint:
        return {"status": "up_to_date", "legacy": str(legacy)}
    result = merge(str(canonical), str(legacy))
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump({
            "schema": 1,
            "legacy": str(legacy),
            "legacy_fingerprint": fingerprint,
            "migrated_at": time.time(),
            "last_result": result,
        }, handle, ensure_ascii=False, indent=2)
    return {"status": "merged", **result}
