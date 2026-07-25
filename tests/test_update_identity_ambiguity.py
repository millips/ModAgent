"""Similar Nexus titles stay blocked until the user confirms a stable ID."""

import json
import os
import tempfile
import types

from modagent import db, nexus, source_alignment, tools
from modagent.sources import thunderstore


root = tempfile.mkdtemp(prefix="modagent-update-identity-")
db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
db.add_mod(db.InstalledMod(
    id="local_auto_forager",
    name="AutoForager",
    version="3.8.0",
    snapshot_id="",
    files_installed=json.dumps([
        os.path.join(root, "Mods", "AutoForager", "AutoForager.dll"),
    ]),
    installed_by="imported",
    game_slug="stardewvalley",
))

cfg = types.SimpleNamespace(
    game_name="Stardew Valley",
    game_slug="stardewvalley",
    game_id=1303,
    game_root=root,
    nexus_api_key="key",
    tavily_api_key="tvly",
    chrome_cdp_port=18888,
    tier="pro",
    manual_mod_dirs={},
)

details = {
    7736: {
        "mod_id": 7736,
        "name": "Auto Forager (previously Auto Shaker)",
        "author": "Jag3Dagster",
        "version": "4.1.0",
        "summary": "Automatically harvests forage and machines.",
        "description": "Complete verified description for Nexus 7736.",
        "dependencies": [2400],
        "updated_at": "2026-07-01",
    },
    47161: {
        "mod_id": 47161,
        "name": "AutoForager",
        "author": "DebugDev",
        "version": "0.5.3",
        "summary": "A different automatic foraging project.",
        "description": "Complete verified description for Nexus 47161.",
        "dependencies": [],
        "updated_at": "2026-06-01",
    },
}

old_community = thunderstore.find_community
old_search = nexus.search
old_detail = nexus.get_detail
old_get = nexus.get_mod
thunderstore.find_community = lambda _name: None
nexus.search = lambda *_args, **_kwargs: [
    {
        "mod_id": 47161,
        "name": "AutoForager",
        "version": "0.5.3",
        "summary": "Search summary 47161",
    },
    {
        "mod_id": 7736,
        "name": "Auto Forager (previously Auto Shaker)",
        "version": "4.1.0",
        "summary": "Search summary 7736",
    },
]
nexus.get_detail = lambda mod_id, *_args, **_kwargs: details[int(mod_id)]
nexus.get_mod = lambda mod_id, *_args, **_kwargs: {
    **details[int(mod_id)],
    "dependencies": [{"mod_id": value} for value in details[int(mod_id)]["dependencies"]],
}

try:
    aligned = source_alignment.align_installed_mods(cfg)
    assert aligned["summary"]["bound"] == 0, aligned
    assert aligned["summary"]["ambiguous"] == 1, aligned
    candidates = aligned["ambiguous"][0]["candidates"]
    assert {item["source_key"] for item in candidates} == {"7736", "47161"}
    assert all(item["detail_verified"] for item in candidates)
    assert all(item["description"].startswith("Complete verified") for item in candidates)
    assert db.get_mod_source_binding(
        "local_auto_forager", "stardewvalley"
    ) is None

    preview = json.loads(tools.execute(
        "mod_source_bind",
        {
            "local_mod_id": "local_auto_forager",
            "nexus_mod_id": 7736,
        },
        cfg,
    ))
    assert preview["requires_confirmation"] is True
    assert preview["preview"]["nexus"]["mod_id"] == 7736

    bound = json.loads(tools.execute(
        "mod_source_bind",
        {
            "local_mod_id": "local_auto_forager",
            "nexus_mod_id": 7736,
            "confirmed": True,
        },
        cfg,
    ))
    assert bound["bound"] is True
    binding = db.get_mod_source_binding(
        "local_auto_forager", "stardewvalley"
    )
    assert binding["source_key"] == "7736"
    assert binding["match_method"] == "user_confirmed"
    metadata = json.loads(binding["metadata"])
    assert metadata["description"].startswith("Complete verified")

    checked = json.loads(tools.execute("mod_update_check", {}, cfg))
    row = next(
        item for item in checked["items"]
        if item["mod_id"] == "local_auto_forager"
    )
    assert row["source_key"] == "7736"
    assert row["match_method"] == "user_confirmed"
    assert row["status"] == "update_available"
finally:
    thunderstore.find_community = old_community
    nexus.search = old_search
    nexus.get_detail = old_detail
    nexus.get_mod = old_get

print("UPDATE IDENTITY AMBIGUITY TESTS PASSED")
