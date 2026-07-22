"""Update checks are concurrent and also backfill dependency metadata."""
import json
import os
import tempfile
import threading
import time
import types

import modagent.config as config


TMP = tempfile.mkdtemp()
config.CONFIG_DIR = os.path.join(TMP, "cfg")
os.makedirs(config.CONFIG_DIR, exist_ok=True)

import modagent.db as db
from modagent import tools


db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()
for mod_id, version in (("1", "1.0"), ("2", "2.0"), ("src_local", "1.0")):
    db.add_mod(db.InstalledMod(
        id=mod_id, name=f"Mod {mod_id}", version=version, snapshot_id="",
        game_slug="repo",
    ))
db.upsert_mod_source_binding(
    "repo", "src_local", "nexus", "3",
    "https://www.nexusmods.com/repo/mods/3", .99, "exact_name", "1.1",
)

active = 0
max_active = 0
lock = threading.Lock()
real_get_mod = tools.nexus.get_mod


def fake_get_mod(mod_id, game_slug, api_key, cdp_port=18888):
    global active, max_active
    with lock:
        active += 1
        max_active = max(max_active, active)
    time.sleep(0.05)
    with lock:
        active -= 1
    return {
        "mod_id": mod_id,
        "name": f"Mod {mod_id}",
        "version": "1.1" if mod_id == 1 else "2.0",
        "dependencies": [{"mod_id": 99 + mod_id}],
    }


tools.nexus.get_mod = fake_get_mod
cfg = types.SimpleNamespace(
    nexus_api_key="key", game_slug="repo", game_id=1, game_root=TMP,
    tier="free", chrome_cdp_port=18888,
)
result = json.loads(tools.execute("mod_update_check", {}, cfg))
tools.nexus.get_mod = real_get_mod

assert max_active >= 2
assert result["checked_nexus"] == 3
assert result["unchecked_non_nexus"] == 0
assert result["dependencies_refreshed"] == 3
assert result["failed_checks"] == []
assert result["updates_available"][0]["mod_id"] == "1"
assert any(item["mod_id"] == "src_local" for item in result["updates_available"])
assert db.parse_dependencies(db.get_mod("1", "repo").dependencies) == ["100"]
assert db.parse_dependencies(db.get_mod("2", "repo").dependencies) == ["101"]

print("ALL PASS")
