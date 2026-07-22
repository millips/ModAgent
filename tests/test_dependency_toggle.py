"""Dependency-aware enable/disable safety gate regression test."""
import json
import os
import tempfile
import types

import modagent.config as config


TMP = tempfile.mkdtemp()
config.CONFIG_DIR = os.path.join(TMP, "cfg")
os.makedirs(config.CONFIG_DIR, exist_ok=True)

import modagent.db as db
import modagent.installer as installer
from modagent import tools


db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()
GAME = os.path.join(TMP, "Game")
os.makedirs(GAME, exist_ok=True)


def write_file(name):
    path = os.path.join(GAME, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(name)
    return path


def add_mod(mod_id, dependencies=None, disabled=False):
    path = write_file(f"{mod_id}.pak")
    if disabled:
        os.rename(path, path + ".disabled")
    db.add_mod(db.InstalledMod(
        id=mod_id, name=f"Mod {mod_id}", version="1", snapshot_id="",
        files_installed=json.dumps([path]), dependencies=json.dumps(dependencies or []),
        game_slug="repo",
    ))
    return path


A = add_mod("A")
B = add_mod("B", ["A"])
C = add_mod("C", ["B"])
D = add_mod("D", ["A-extra"])
E = add_mod("E", ["missing-framework"], disabled=True)

cfg = types.SimpleNamespace(
    nexus_api_key="", game_slug="repo", game_id=0, game_root=GAME,
    tier="free", chrome_cdp_port=18888,
)


def execute(name, args):
    return json.loads(tools.execute(name, args, cfg))


# Exact ID matching: D depends on A-extra, not A.
assert [item["id"] for item in db.get_dependents("A", "repo")] == ["B"]
assert db.parse_dependencies([{"mod_id": 123}, "456", {"mod_id": 123}]) == ["123", "456"]

# Preview is non-mutating and exposes the full dependent chain deepest-first.
preview = execute("mod_disable", {"mod_id": "A"})
assert preview["requires_confirmation"] is True
assert [item["id"] for item in preview["dependents"]] == ["C", "B"]
assert all(os.path.exists(path) for path in [A, B, C, D])

# Confirmed disable cascades to dependents but not a substring-matched neighbor.
result = execute("mod_disable", {"mod_id": "A", "confirmed": True,
                                 "confirmation_token": preview["confirmation_token"]})
assert [item["id"] for item in result["disabled_mods"]] == ["C", "B", "A"]
assert all(os.path.exists(path + ".disabled") for path in [A, B, C])
assert os.path.exists(D)

# Enable preview and execution use the inverse order: foundations first.
preview = execute("mod_enable", {"mod_id": "C"})
assert preview["requires_confirmation"] is True
assert [item["id"] for item in preview["dependencies"]] == ["A", "B"]
result = execute("mod_enable", {"mod_id": "C", "confirmed": True})
assert [item["id"] for item in result["enabled_mods"]] == ["A", "B", "C"]
assert all(os.path.exists(path) for path in [A, B, C])

# A mid-chain rename failure is rolled back instead of leaving a half-disabled graph.
real_rename = installer.os.rename
def fail_on_b(source, destination):
    if source == B:
        raise PermissionError("simulated file lock")
    return real_rename(source, destination)
installer.os.rename = fail_on_b
preview = execute("mod_disable", {"mod_id": "A"})
failed = execute("mod_disable", {"mod_id": "A", "confirmed": True,
                                  "confirmation_token": preview["confirmation_token"]})
installer.os.rename = real_rename
assert "error" in failed and failed["rolled_back"] is True
assert all(os.path.exists(path) and not os.path.exists(path + ".disabled") for path in [A, B, C])

# Missing dependencies block the operation and leave disk state untouched.
blocked = execute("mod_enable", {"mod_id": "E", "confirmed": True})
assert blocked["blocked"] is True
assert blocked["missing_dependencies"] == ["missing-framework"]
assert os.path.exists(E + ".disabled")

# Cycles terminate safely and never include the root twice.
X = add_mod("X", ["Y"])
Y = add_mod("Y", ["X"])
assert [item.id for item in db.get_dependency_chain("X", "repo")[0]] == ["Y"]
assert [item.id for item in db.get_dependent_chain("X", "repo")] == ["Y"]

# Cross-source mappings are preview-gated and only accept installed local IDs.
preview = execute("mod_dependency_set", {"mod_id": "C", "dependencies": ["A"]})
assert preview["requires_confirmation"] is True
assert db.parse_dependencies(db.get_mod("C", "repo").dependencies) == ["B"]
updated = execute("mod_dependency_set", {"mod_id": "C", "dependencies": ["A"], "confirmed": True})
assert updated["updated"] is True
assert db.parse_dependencies(db.get_mod("C", "repo").dependencies) == ["A"]
invalid = execute("mod_dependency_set", {"mod_id": "C", "dependencies": ["not-installed"], "confirmed": True})
assert "error" in invalid and invalid["missing_dependencies"] == ["not-installed"]

print("ALL PASS")
