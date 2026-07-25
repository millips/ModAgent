"""SMAPI manifest metadata wins over generic folder-name inventory."""

import json
import os
import tempfile

from modagent import db, scanner


temp = tempfile.mkdtemp(prefix="modagent-local-manifest-")
game = os.path.join(temp, "Stardew Valley")
mod_dir = os.path.join(game, "Mods", "NPCMapLocations")
os.makedirs(mod_dir)
with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as handle:
    json.dump({
        "Name": "NPC Map Locations",
        "UniqueID": "Bouhm.NPCMapLocations",
        "Version": "3.5.2",
        "EntryDll": "NPCMapLocations.dll",
    }, handle)
with open(os.path.join(mod_dir, "NPCMapLocations.dll"), "wb") as handle:
    handle.write(b"test")

old_db = db.DB_FILE
try:
    db.DB_FILE = os.path.join(temp, "state.db")
    db.init_db()
    report = scanner.scan_existing_mods(
        game, "stardewvalley", "", game_instance_id="gi_test"
    )
finally:
    db.DB_FILE = old_db

rows = [
    item for item in report["identified"]
    if item["name"] in {"NPC Map Locations", "NPCMapLocations"}
]
assert len(rows) == 1, rows
assert rows[0]["name"] == "NPC Map Locations"
assert rows[0]["version"] == "3.5.2"
assert rows[0]["confidence"] == "local_manifest"
assert rows[0]["local_unique_id"] == "Bouhm.NPCMapLocations"

print("ALL PASS")
