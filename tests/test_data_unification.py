import json
import os
import sqlite3
import tempfile

from modagent import data_unification


def make_db(root, session_id, updated, snapshot_id):
    db = os.path.join(root, "state.db")
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE sessions (id TEXT PRIMARY KEY,title TEXT,game_slug TEXT,created_at REAL,updated_at REAL,messages TEXT,ui_state TEXT);
    CREATE TABLE installed_mods (id TEXT,name TEXT,version TEXT,snapshot_id TEXT,load_order INTEGER,file_id INTEGER,installed_at REAL,files_installed TEXT,dependencies TEXT,installed_by TEXT,game_slug TEXT,PRIMARY KEY(game_slug,id));
    CREATE TABLE snapshots (id TEXT PRIMARY KEY,timestamp REAL,files TEXT,trigger_mod_id TEXT,trigger_mod_name TEXT,game_slug TEXT);
    CREATE TABLE operation_log (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp REAL,action TEXT,details TEXT);
    CREATE TABLE mod_source_bindings (game_slug TEXT,mod_id TEXT,source TEXT,source_key TEXT,source_url TEXT,confidence REAL,match_method TEXT,latest_version TEXT,metadata TEXT,bound_at REAL,last_checked_at REAL,PRIMARY KEY(game_slug,mod_id));
    CREATE TABLE mod_catalog_notes (game_slug TEXT,mod_id TEXT,localized_name TEXT,summary TEXT,evidence_kind TEXT,confidence TEXT,source_fingerprint TEXT,updated_at REAL,PRIMARY KEY(game_slug,mod_id));
    CREATE TABLE custom_domains (game_slug TEXT,path TEXT,added_at REAL,UNIQUE(game_slug,path));
    """)
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", (session_id, session_id, "sf6", 1, updated, "[]", "{}"))
    con.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", (snapshot_id, updated, "[]", "", "test", "sf6"))
    con.execute("INSERT INTO operation_log(timestamp,action,details) VALUES (?,?,?)", (updated, "install", session_id))
    con.commit(); con.close()


with tempfile.TemporaryDirectory() as temp:
    canonical, legacy = os.path.join(temp, "main"), os.path.join(temp, "beta")
    os.makedirs(canonical); os.makedirs(legacy); os.makedirs(os.path.join(legacy, "snapshots"))
    make_db(canonical, "stable", 10, "snap-stable")
    make_db(legacy, "beta", 20, "snap-beta")
    result = data_unification.merge(canonical, legacy)
    con = sqlite3.connect(os.path.join(canonical, "state.db"))
    assert con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0] == 2
    con.close()
    assert os.path.isfile(os.path.join(result["backup"], "canonical-state.db"))
    roots = json.load(open(os.path.join(canonical, "legacy-snapshot-roots.json"), encoding="utf-8"))
    assert os.path.join(legacy, "snapshots") in roots["roots"]

with tempfile.TemporaryDirectory() as temp:
    canonical, legacy = os.path.join(temp, ".modagent"), os.path.join(temp, ".modagent-beta")
    os.makedirs(canonical); os.makedirs(legacy)
    make_db(canonical, "stable", 10, "snap-stable")
    make_db(legacy, "beta", 20, "snap-beta")
    first = data_unification.migrate_default_beta_history(canonical)
    second = data_unification.migrate_default_beta_history(canonical)
    assert first["status"] == "merged"
    assert second["status"] == "up_to_date"
print("DATA UNIFICATION TEST PASSED")
