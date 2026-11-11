"""One physical Mod must not become two inventory/install identities."""
import json
import os
import tempfile
import zipfile

from modagent import db, downloader, games, nexus, scanner, snapshot, tools
from modagent.config import Config, Tier
from modagent.inventory_match import find_installed_duplicate


root = tempfile.mkdtemp()
db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
game = os.path.join(root, "REPO")
plugin = os.path.join(
    game, "BepInEx", "plugins", "39_MoneyValueTracker", "MapMoneyMod.dll",
)
os.makedirs(os.path.dirname(plugin), exist_ok=True)
with open(plugin, "wb") as handle:
    handle.write(b"existing")

cfg = Config(
    game_name="R.E.P.O.", game_slug="repo", game_instance_id="repo",
    game_root=game, game_id=1234, nexus_api_key="key", tier=Tier.PRO,
)

# Formal Nexus row and the historical scanner alias point at exactly one DLL.
db.add_mod(db.InstalledMod(
    id="39", name="MoneyValueTracker", version="1.0.0", snapshot_id="snap",
    files_installed=json.dumps([plugin]), installed_by="modagent",
    game_slug="repo",
))
db.add_mod(db.InstalledMod(
    id="local_alias", name="39_MoneyValueTracker", version="unknown",
    snapshot_id="", files_installed=json.dumps([plugin]),
    installed_by="imported", game_slug="repo",
))

refreshed = tools.refresh_local_inventory(cfg)
merged = refreshed["aliases_merged"]
assert len(merged) == 1, refreshed
saved = db.get_installed_mods("repo")
assert [(item.id, item.name) for item in saved] == [
    ("39", "MoneyValueTracker"),
], saved
assert os.path.isfile(plugin), "metadata merge must never delete the DLL"

# A fresh scan sees the file but must not import the package directory again.
scanned = scanner.scan_existing_mods(game, "repo", "")
assert scanned["identified"] == [], scanned
assert scanner.import_mods(scanned["identified"]) == 0
assert len(db.get_installed_mods("repo")) == 1

# The direct scanner entry point must repair historical aliases too.  This path
# must not rely on the download preflight wrapper.
db.add_mod(db.InstalledMod(
    id="local_alias_again", name="39_MoneyValueTracker", version="unknown",
    snapshot_id="", files_installed=json.dumps([plugin]),
    installed_by="imported", game_slug="repo",
))
direct_scan = scanner.scan_existing_mods(game, "repo", "")
assert direct_scan["identified"] == [], direct_scan
assert [(item.id, item.name) for item in db.get_installed_mods("repo")] == [
    ("39", "MoneyValueTracker"),
]

# A custom install can record the package payload while a later loader scan
# adds a generated file and reports the manifest name.  Shared DLL evidence
# plus the normalized name must still collapse it to one Mod.
gmcm_dll = os.path.join(
    game, "BepInEx", "plugins", "GenericModConfigMenu", "GMCM.dll",
)
gmcm_cfg = os.path.join(
    game, "BepInEx", "config", "GMCM.cfg",
)
os.makedirs(os.path.dirname(gmcm_dll), exist_ok=True)
os.makedirs(os.path.dirname(gmcm_cfg), exist_ok=True)
open(gmcm_dll, "wb").close()
open(gmcm_cfg, "wb").close()
db.add_mod(db.InstalledMod(
    id="custom_5098_1145906_Generic_Mod_Config_Menu_GMCM",
    name="Generic Mod Config Menu (GMCM)", version="", snapshot_id="",
    files_installed=json.dumps([gmcm_dll]), installed_by="custom",
    game_slug="repo",
))
db.add_mod(db.InstalledMod(
    id="local_gmcm", name="GenericModConfigMenu", version="unknown",
    snapshot_id="", files_installed=json.dumps([gmcm_dll, gmcm_cfg]),
    installed_by="imported", game_slug="repo",
))
merged_semantic = db.merge_duplicate_inventory_rows("repo")
assert any(item["reason"] == "shared_file_matching_name" for item in merged_semantic), merged_semantic
assert db.get_mod("local_gmcm", "repo") is None
db.remove_mod("custom_5098_1145906_Generic_Mod_Config_Menu_GMCM", "repo")

# A Nexus archive downloaded by ModAgent carries a numeric Mod ID even before
# a browser detail page is available.  It must become an immediate source
# binding after install rather than falling back to a future manual alignment.
original_provenance_reader = downloader.read_download_provenance
downloader.read_download_provenance = lambda _path: {
    "source": "nexus", "game_slug": "repo", "source_key": "5098",
}
try:
    nexus_provenance = tools._download_source_provenance("ignored.zip", "repo")
finally:
    downloader.read_download_provenance = original_provenance_reader
assert nexus_provenance["source"] == "nexus", nexus_provenance
assert nexus_provenance["source_url"] == "https://www.nexusmods.com/repo/mods/5098", nexus_provenance
db.add_mod(db.InstalledMod(
    id="custom_5098_1145906_legacy", name="legacy nexus install",
    version="1.0", snapshot_id="", files_installed="[]", installed_by="custom",
    game_slug="repo",
))
backfilled = db.backfill_custom_nexus_bindings("repo")
assert backfilled == [{"mod_id": "custom_5098_1145906_legacy", "source_key": "5098"}], backfilled
assert db.get_mod_source_binding("custom_5098_1145906_legacy", "repo")["source"] == "nexus"
db.remove_mod("custom_5098_1145906_legacy", "repo")

# The visible "reconcile" action includes identity reconciliation, not only a
# missing-file check.
db.add_mod(db.InstalledMod(
    id="local_reconcile_alias", name="39_MoneyValueTracker",
    version="unknown", snapshot_id="",
    files_installed=json.dumps([plugin]), installed_by="imported",
    game_slug="repo",
))
from modagent import api
reconciled = api.mods_reconcile("repo")
assert reconciled["duplicates_merged"] == 1, reconciled
assert reconciled["issues"] == [], reconciled
assert [(item.id, item.name) for item in db.get_installed_mods("repo")] == [
    ("39", "MoneyValueTracker"),
]

# Even a legacy-only alias is an exact match when its folder begins with the
# stable Nexus ID.
db.remove_mod("39", "repo")
db.add_mod(db.InstalledMod(
    id="local_only", name="39_MoneyValueTracker", version="unknown",
    snapshot_id="", files_installed=json.dumps([plugin]),
    installed_by="imported", game_slug="repo",
))
matched = find_installed_duplicate(
    "repo", "nexus", "39", target_name="MoneyValueTracker",
)
assert matched and matched.id == "local_only", matched

# Recommendation confirmation must stop before snapshot/write when the same
# physical Mod is already present under its local alias.
archive = os.path.join(root, "39_MoneyValueTracker.zip")
with zipfile.ZipFile(archive, "w") as handle:
    handle.writestr("MapMoneyMod.dll", b"replacement")

original_detail = nexus.get_detail
original_alive = games.verify_game_alive
original_snapshot = snapshot.snapshot_create
nexus.get_detail = lambda *_args, **_kwargs: {
    "mod_id": 39,
    "name": "MoneyValueTracker",
    "required_loader": "BepInEx",
    "dependencies": [],
    "dependency_labels": [],
}
games.verify_game_alive = lambda *_args, **_kwargs: {
    "alive": True, "engine": "unity",
}
snapshot.snapshot_create = lambda *_args, **_kwargs: (
    _ for _ in ()
).throw(AssertionError("duplicate install must stop before snapshot"))
try:
    result = json.loads(tools.execute(
        "mod_install",
        {
            "mod_id": 39,
            "local_path": archive,
            "require_verified_preflight": True,
        },
        cfg,
    ))
finally:
    nexus.get_detail = original_detail
    games.verify_game_alive = original_alive
    snapshot.snapshot_create = original_snapshot

assert result["already_installed"] is True, result
assert result["install_skipped"] is True, result
with open(plugin, "rb") as handle:
    assert handle.read() == b"existing"

# An explicit list reconciliation must synchronise an externally deleted Mod
# out of the visible inventory, while the ordinary diagnostic mode keeps its
# conservative no-write behaviour.
deleted_file = os.path.join(game, "BepInEx", "plugins", "deleted", "gone.dll")
db.add_mod(db.InstalledMod(
    id="externally_deleted", name="Externally deleted Mod", version="1.0",
    snapshot_id="", files_installed=json.dumps([deleted_file]),
    installed_by="imported", game_slug="repo",
))
diagnostic = api.mods_reconcile("repo")
assert any(item["mod_id"] == "externally_deleted" for item in diagnostic["issues"]), diagnostic
assert db.get_mod("externally_deleted", "repo") is not None
synchronised = api.mods_reconcile("repo", sync_missing=True)
assert [item["mod_id"] for item in synchronised["removed_missing"]] == ["externally_deleted"], synchronised
assert db.get_mod("externally_deleted", "repo") is None

print("PHYSICAL INVENTORY IDENTITY TESTS PASSED")
