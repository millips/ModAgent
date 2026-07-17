import json
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Optional
from .config import CONFIG_DIR, ensure_config_dir

DB_FILE = os.path.join(CONFIG_DIR, "state.db")


@dataclass
class InstalledMod:
    id: str
    name: str
    version: str
    snapshot_id: str
    load_order: int = 0
    file_id: int = 0
    installed_at: float = 0.0
    files_installed: str = "[]"
    dependencies: str = "[]"
    installed_by: str = "modagent"
    game_slug: str = ""


@dataclass
class Snapshot:
    id: str
    timestamp: float
    files: str
    trigger_mod_id: str = ""
    trigger_mod_name: str = ""
    game_slug: str = ""


def get_conn() -> sqlite3.Connection:
    ensure_config_dir()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS installed_mods (
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            snapshot_id TEXT,
            load_order INTEGER DEFAULT 0,
            file_id INTEGER DEFAULT 0,
            installed_at REAL DEFAULT 0,
            files_installed TEXT DEFAULT '[]',
            dependencies TEXT DEFAULT '[]',
            installed_by TEXT DEFAULT 'modagent',
            game_slug TEXT DEFAULT '',
            PRIMARY KEY (game_slug, id)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            files TEXT NOT NULL,
            trigger_mod_id TEXT DEFAULT '',
            trigger_mod_name TEXT DEFAULT '',
            game_slug TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS operation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            action TEXT NOT NULL,
            details TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            game_slug TEXT DEFAULT '',
            created_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0,
            messages TEXT DEFAULT '[]'
        );
        -- T2:自定义安装(mod_install_custom)的落点登记。精确文件(相对 game_root 正斜杠),
        -- 由 snapshot._auto_detect_specs 并入快照域,保证非常规落点也能被回滚覆盖(铁律6)。
        CREATE TABLE IF NOT EXISTS custom_domains (
            game_slug TEXT NOT NULL,
            path TEXT NOT NULL,
            added_at REAL DEFAULT 0,
            UNIQUE(game_slug, path)
        );
    """)
    try:
        conn.execute("ALTER TABLE installed_mods ADD COLUMN files_installed TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE installed_mods ADD COLUMN dependencies TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE installed_mods ADD COLUMN installed_by TEXT DEFAULT 'modagent'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN game_slug TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE installed_mods ADD COLUMN game_slug TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # v1.0 migration: Nexus/Workshop IDs are only unique inside a game.
    pk_cols = [r[1] for r in conn.execute("PRAGMA table_info(installed_mods)") if r[5]]
    if pk_cols != ["id", "game_slug"] and pk_cols != ["game_slug", "id"]:
        conn.executescript("""
            ALTER TABLE installed_mods RENAME TO installed_mods_legacy;
            CREATE TABLE installed_mods (
                id TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
                snapshot_id TEXT, load_order INTEGER DEFAULT 0,
                file_id INTEGER DEFAULT 0, installed_at REAL DEFAULT 0,
                files_installed TEXT DEFAULT '[]', dependencies TEXT DEFAULT '[]',
                installed_by TEXT DEFAULT 'modagent', game_slug TEXT DEFAULT '',
                PRIMARY KEY (game_slug, id)
            );
            INSERT INTO installed_mods
            SELECT id,name,version,snapshot_id,load_order,file_id,installed_at,
                   files_installed,dependencies,installed_by,COALESCE(game_slug,'')
            FROM installed_mods_legacy;
            DROP TABLE installed_mods_legacy;
        """)
    conn.commit()
    conn.close()


def add_mod(mod: InstalledMod):
    conn = get_conn()
    mod.installed_at = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO installed_mods VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (mod.id, mod.name, mod.version, mod.snapshot_id, mod.load_order,
         mod.file_id, mod.installed_at, mod.files_installed, mod.dependencies, mod.installed_by, mod.game_slug),
    )
    _log(conn, "install", json.dumps(asdict(mod)))
    conn.commit()
    conn.close()


def remove_mod(mod_id: str, game_slug: str = ""):
    conn = get_conn()
    if game_slug:
        conn.execute("DELETE FROM installed_mods WHERE id=? AND game_slug=?", (mod_id, game_slug))
    else:
        conn.execute("DELETE FROM installed_mods WHERE id=?", (mod_id,))
    _log(conn, "uninstall", json.dumps({"mod_id": mod_id, "game_slug": game_slug}))
    conn.commit()
    conn.close()


def get_mod(mod_id: str, game_slug: str = "") -> Optional[InstalledMod]:
    conn = get_conn()
    if game_slug:
        row = conn.execute("SELECT * FROM installed_mods WHERE id=? AND game_slug=?",
                           (mod_id, game_slug)).fetchone()
    else:
        row = conn.execute("SELECT * FROM installed_mods WHERE id=? ORDER BY installed_at DESC",
                           (mod_id,)).fetchone()
    conn.close()
    return InstalledMod(**dict(row)) if row else None


def update_mod(mod: InstalledMod):
    conn = get_conn()
    conn.execute(
        "UPDATE installed_mods SET name=?, version=?, snapshot_id=?, load_order=?,"
        "file_id=?, installed_at=?, files_installed=?, dependencies=?, installed_by=? WHERE id=? AND game_slug=?",
        (mod.name, mod.version, mod.snapshot_id, mod.load_order,
         mod.file_id, mod.installed_at, mod.files_installed, mod.dependencies, mod.installed_by, mod.id, mod.game_slug),
    )
    conn.commit()
    conn.close()


def get_installed_mods(game_slug: str = "") -> list:
    conn = get_conn()
    if game_slug:
        rows = conn.execute(
            "SELECT * FROM installed_mods WHERE game_slug=? ORDER BY load_order, installed_at",
            (game_slug,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM installed_mods ORDER BY load_order, installed_at").fetchall()
    conn.close()
    return [InstalledMod(**dict(r)) for r in rows]


def get_shared_files(mod_id: str, files: list, game_slug: str = "") -> set:
    """返回 files 中【也被除 mod_id 外的其他已装 mod 拥有】的文件集合。
    用于卸载保护:这些是共享文件,卸载本 mod 时不应从磁盘删除。
    返回值为 normcase 后的绝对路径集合,便于调用方比对。
    """
    import os as _os
    import json as _json
    target = {_os.path.normcase(_os.path.abspath(f)) for f in (files or [])}
    if not target:
        return set()
    shared = set()
    for m in get_installed_mods(game_slug):
        if str(m.id) == str(mod_id):
            continue
        try:
            other = m.files_installed
            other = _json.loads(other) if isinstance(other, str) else (other or [])
        except Exception:
            other = []
        for f in other:
            key = _os.path.normcase(_os.path.abspath(f))
            if key in target:
                shared.add(key)
    return shared


def get_dependents(mod_id: str, game_slug: str = "") -> list:
    """Return direct dependents using exact IDs instead of substring matching."""
    target = str(mod_id)
    result = []
    for mod in get_installed_mods(game_slug):
        if target in parse_dependencies(mod.dependencies):
            result.append({"id": mod.id, "name": mod.name, "version": mod.version})
    return result


def parse_dependencies(value) -> list[str]:
    """Normalize a dependency JSON field to a de-duplicated string ID list."""
    try:
        values = json.loads(value) if isinstance(value, str) else (value or [])
    except (TypeError, ValueError, json.JSONDecodeError):
        values = []
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for item in values:
        dep_id = str(item.get("mod_id") if isinstance(item, dict) else item).strip()
        if dep_id and dep_id != "None" and dep_id not in seen:
            seen.add(dep_id)
            result.append(dep_id)
    return result


def get_dependent_chain(mod_id: str, game_slug: str = "") -> list[InstalledMod]:
    """Return transitive dependents deepest-first, suitable for cascade disable."""
    mods = get_installed_mods(game_slug)
    by_id = {str(mod.id): mod for mod in mods}
    reverse = {}
    for mod in mods:
        for dependency_id in parse_dependencies(mod.dependencies):
            reverse.setdefault(dependency_id, []).append(str(mod.id))
    root_id = str(mod_id)
    visited = {root_id}
    ordered = []

    def visit(current_id: str):
        for dependent_id in reverse.get(current_id, []):
            if dependent_id in visited:
                continue
            visited.add(dependent_id)
            visit(dependent_id)
            if dependent_id in by_id:
                ordered.append(by_id[dependent_id])

    visit(root_id)
    return ordered


def get_dependency_chain(mod_id: str, game_slug: str = "") -> tuple[list[InstalledMod], list[str]]:
    """Return installed dependencies deepest-first plus unresolved dependency IDs."""
    mods = get_installed_mods(game_slug)
    by_id = {str(mod.id): mod for mod in mods}
    root_id = str(mod_id)
    visited = {root_id}
    ordered = []
    missing = []
    missing_seen = set()

    def visit(current_id: str):
        current = by_id.get(current_id)
        if not current:
            return
        for dependency_id in parse_dependencies(current.dependencies):
            if dependency_id in visited:
                continue
            visited.add(dependency_id)
            dependency = by_id.get(dependency_id)
            if not dependency:
                if dependency_id not in missing_seen:
                    missing_seen.add(dependency_id)
                    missing.append(dependency_id)
                continue
            visit(dependency_id)
            ordered.append(dependency)

    visit(root_id)
    return ordered, missing


def get_max_load_order(game_slug: str = "") -> int:
    conn = get_conn()
    if game_slug:
        row = conn.execute("SELECT COALESCE(MAX(load_order), -1) as mx FROM installed_mods WHERE game_slug=?",
                           (game_slug,)).fetchone()
    else:
        row = conn.execute("SELECT COALESCE(MAX(load_order), -1) as mx FROM installed_mods").fetchone()
    conn.close()
    return row["mx"]


def add_snapshot(snap: Snapshot):
    conn = get_conn()
    conn.execute(
        "INSERT INTO snapshots VALUES (?,?,?,?,?,?)",
        (snap.id, snap.timestamp, snap.files, snap.trigger_mod_id, snap.trigger_mod_name, snap.game_slug),
    )
    _log(conn, "snapshot_create", json.dumps(asdict(snap)))
    conn.commit()
    conn.close()


def delete_snapshot(snap_id: str):
    conn = get_conn()
    conn.execute("DELETE FROM snapshots WHERE id=?", (snap_id,))
    conn.commit()
    conn.close()


# ── T2:自定义安装落点登记(mod_install_custom 用;快照域并入见 snapshot._auto_detect_specs)──

def add_custom_domain_files(game_slug: str, paths: list) -> None:
    """登记自定义落点(精确文件,相对 game_root 正斜杠)进该游戏的快照域。幂等。"""
    if not game_slug or not paths:
        return
    conn = get_conn()
    now = time.time()
    for p in paths:
        conn.execute(
            "INSERT OR IGNORE INTO custom_domains (game_slug, path, added_at) VALUES (?,?,?)",
            (game_slug, p.replace("\\", "/"), now))
    conn.commit()
    conn.close()


def get_custom_domain_files(game_slug: str) -> list:
    """该游戏登记过的自定义落点(精确相对路径,正斜杠)。供快照域并入。"""
    if not game_slug:
        return []
    conn = get_conn()
    rows = conn.execute(
        "SELECT path FROM custom_domains WHERE game_slug=? ORDER BY path",
        (game_slug,)).fetchall()
    conn.close()
    return [r["path"] for r in rows]


def remove_custom_domain_files(game_slug: str, paths: list) -> None:
    """撤销登记(卸载 custom mod 时清理,避免登记表冗余堆积)。"""
    if not game_slug or not paths:
        return
    conn = get_conn()
    for p in paths:
        conn.execute("DELETE FROM custom_domains WHERE game_slug=? AND path=?",
                     (game_slug, p.replace("\\", "/")))
    conn.commit()
    conn.close()


def get_snapshot(snap_id: str) -> Optional[Snapshot]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    conn.close()
    return Snapshot(**dict(row)) if row else None


def list_snapshots(game_slug: str = "") -> list:
    conn = get_conn()
    if game_slug:
        rows = conn.execute("SELECT * FROM snapshots WHERE game_slug=? ORDER BY timestamp DESC", (game_slug,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM snapshots ORDER BY timestamp DESC").fetchall()
    conn.close()
    return [Snapshot(**dict(r)) for r in rows]


def get_operation_log(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM operation_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _log(conn: sqlite3.Connection, action: str, details: str):
    conn.execute("INSERT INTO operation_log (timestamp, action, details) VALUES (?,?,?)", (time.time(), action, details))


# ── Sessions ──

def list_sessions(game_slug: str = "") -> list:
    conn = get_conn()
    if game_slug:
        rows = conn.execute("SELECT id, title, game_slug, created_at, updated_at FROM sessions WHERE game_slug=? ORDER BY updated_at DESC", (game_slug,)).fetchall()
    else:
        rows = conn.execute("SELECT id, title, game_slug, created_at, updated_at FROM sessions ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_session(sid: str, title: str = "", game_slug: str = "") -> dict:
    now = time.time()
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
        (sid, title, game_slug, now, now, "[]"),
    )
    conn.commit()
    conn.close()
    return {"id": sid, "title": title, "game_slug": game_slug, "created_at": now, "updated_at": now}


def update_session_title(sid: str, title: str):
    conn = get_conn()
    conn.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, time.time(), sid))
    conn.commit()
    conn.close()


def update_session_messages(sid: str, messages: list):
    conn = get_conn()
    conn.execute("UPDATE sessions SET messages=?, updated_at=? WHERE id=?", (json.dumps(messages, ensure_ascii=False), time.time(), sid))
    conn.commit()
    conn.close()


def delete_session(sid: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.commit()
    conn.close()
