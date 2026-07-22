"""A local hash-ID mod can become a Nexus-managed/updateable item."""
import json
import os
import tempfile
import types

from modagent import db, nexus, source_alignment, tools
from modagent.sources import thunderstore


root = tempfile.mkdtemp()
db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
db.add_mod(db.InstalledMod(
    id="local_cet", name="Cyber Engine Tweaks", version="1.0.0",
    snapshot_id="", files_installed=json.dumps([os.path.join(root, "cet.asi")]),
    installed_by="imported", game_slug="cyberpunk2077",
))

cfg = types.SimpleNamespace(
    game_name="Cyberpunk 2077", game_slug="cyberpunk2077", game_id=3333,
    game_root=root, nexus_api_key="key", tavily_api_key="tvly",
    chrome_cdp_port=18888, tier="pro", manual_mod_dirs={},
)
old_community = thunderstore.find_community
old_search = nexus.search
old_get = nexus.get_mod
thunderstore.find_community = lambda _name: None
nexus.search = lambda *_args, **_kwargs: [{
    "mod_id": 107, "name": "Cyber Engine Tweaks", "version": "2.1.0",
}]
nexus.get_mod = lambda *_args, **_kwargs: {
    "mod_id": 107, "name": "Cyber Engine Tweaks", "version": "2.1.0",
    "dependencies": [],
}
try:
    aligned = source_alignment.align_installed_mods(cfg)
    assert aligned["summary"]["bound"] == 1, aligned
    binding = db.get_mod_source_binding("local_cet", "cyberpunk2077")
    assert binding["source"] == "nexus" and binding["source_key"] == "107", binding
    checked = json.loads(tools.execute("mod_update_check", {}, cfg))
    row = next(item for item in checked["items"] if item["mod_id"] == "local_cet")
    assert row["status"] == "update_available" and row["can_update"] is True, row
    assert checked["checked_nexus"] == 1, checked
finally:
    thunderstore.find_community = old_community
    nexus.search = old_search
    nexus.get_mod = old_get

print("NEXUS LOCAL ALIGNMENT TESTS PASSED")
