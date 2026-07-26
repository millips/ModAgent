"""Recommendations distinguish exact installs from same-purpose alternatives."""
import json
import os
import tempfile

from modagent import db
from modagent.inventory_match import functional_family_name
from modagent.recommendation_ui import normalize_recommendations


tmp = tempfile.mkdtemp(prefix="modagent_alternative_")
db.DB_FILE = os.path.join(tmp, "state.db")
db.init_db()
db.add_mod(db.InstalledMod(
    id="local-better-team",
    name="BetterTeamUpgrades",
    version="2.2.1",
    snapshot_id="",
    game_slug="repo",
))

assert functional_family_name("BetterTeamUpgrades") == "sharedupgrades"
assert functional_family_name("Shared Upgrades - Comestic Update") == "sharedupgrades"
assert functional_family_name("Better Map") == ""

payload = normalize_recommendations({
    "recommendations": [{
        "mod_id": 23,
        "name": "Shared Upgrades - Comestic Update",
        "summary": "Keeps the whole team on the same upgrade level.",
        "version": "2.2.2",
        "_detail_verified": True,
        "url": "https://www.nexusmods.com/repo/mods/23",
    }],
}, game_slug="repo")

assert len(payload["items"]) == 1
item = payload["items"][0]
assert item["installed_match_kind"] == "functional_alternative"
assert item["installed_name"] == "BetterTeamUpgrades"
assert item["installable"] is False
assert item["default_selected"] is False
assert "不是版本更新" in item["conflict"]
assert payload["selected_keys"] == []

print("ALL PASS")
