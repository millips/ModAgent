"""mod_update must use the SMAPI installer and persist only Mods/ paths."""

import asyncio
import json
import os
import tempfile
import types
import zipfile

from modagent import db, tools


root = tempfile.mkdtemp(prefix="modagent-stardew-update-")
game = os.path.join(root, "Stardew Valley")
os.makedirs(game)
archive = os.path.join(root, "AutoForager-4.1.0.zip")
with zipfile.ZipFile(archive, "w") as handle:
    handle.writestr("AutoForager/manifest.json", json.dumps({
        "Name": "Auto Forager",
        "Author": "Jag3Dagster",
        "Version": "4.1.0",
        "UniqueID": "J3.AutoForager",
        "EntryDll": "AutoForager.dll",
    }))
    handle.writestr("AutoForager/AutoForager.dll", b"new")
    handle.writestr("AutoForager/i18n/default.json", "{}")

db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
old_file = os.path.join(game, "Mods", "AutoForager-old", "AutoForager.dll")
os.makedirs(os.path.dirname(old_file))
with open(old_file, "wb") as handle:
    handle.write(b"old")
db.add_mod(db.InstalledMod(
    id="local_auto_forager",
    name="Auto Forager",
    version="3.8.0",
    snapshot_id="old",
    files_installed=json.dumps([old_file]),
    installed_by="imported",
    game_slug="stardewvalley",
))
db.upsert_mod_source_binding(
    "stardewvalley",
    "local_auto_forager",
    "nexus",
    "7736",
    "https://www.nexusmods.com/stardewvalley/mods/7736",
    1,
    "user_confirmed",
    "4.1.0",
    {"summary": "Verified"},
)

cfg = types.SimpleNamespace(
    game_name="Stardew Valley",
    game_slug="stardewvalley",
    game_id=1303,
    game_root=game,
    nexus_api_key="key",
    tavily_api_key="",
    chrome_cdp_port=18888,
    tier="pro",
)

originals = {
    "get_main_file": tools.nexus.get_main_file,
    "get_mod": tools.nexus.get_mod,
    "download_mod": tools.downloader.download_mod,
    "cleanup": tools.downloader.cleanup_installed_archive,
    "snapshot_create": tools.snapshot.snapshot_create,
    "uninstall_mod": tools.installer.uninstall_mod,
}


async def fake_download_mod(**_kwargs):
    return {"local_path": archive}


tools.nexus.get_main_file = lambda *_args, **_kwargs: {
    "file_id": 100,
    "version": "4.1.0",
}
tools.nexus.get_mod = lambda *_args, **_kwargs: {
    "mod_id": 7736,
    "name": "Auto Forager (previously Auto Shaker)",
    "version": "4.1.0",
    "dependencies": [],
}
tools.downloader.download_mod = fake_download_mod
tools.downloader.cleanup_installed_archive = lambda _path: {"removed": False}
tools.snapshot.snapshot_create = lambda *_args, **_kwargs: "update-snapshot"
tools.installer.uninstall_mod = lambda *_args, **_kwargs: {
    "removed": [old_file],
    "errors": [],
}

try:
    result = json.loads(tools.execute(
        "mod_update", {"mod_id": "local_auto_forager"}, cfg
    ))
finally:
    tools.nexus.get_main_file = originals["get_main_file"]
    tools.nexus.get_mod = originals["get_mod"]
    tools.downloader.download_mod = originals["download_mod"]
    tools.downloader.cleanup_installed_archive = originals["cleanup"]
    tools.snapshot.snapshot_create = originals["snapshot_create"]
    tools.installer.uninstall_mod = originals["uninstall_mod"]

assert result.get("error") is None, result
assert result["install_handler"] == "stardew_smapi"
assert result["verified_mods"][0]["unique_id"] == "J3.AutoForager"
updated = db.get_mod("local_auto_forager", "stardewvalley")
files = json.loads(updated.files_installed)
mods_root = os.path.realpath(os.path.join(game, "Mods"))
assert files
assert all(
    os.path.commonpath([mods_root, os.path.realpath(path)]) == mods_root
    for path in files
)
assert not any("BepInEx" in path for path in files)
binding = db.get_mod_source_binding(
    "local_auto_forager", "stardewvalley"
)
assert binding["source_key"] == "7736"
assert binding["match_method"] == "user_confirmed"

print("STARDEW UPDATE ROUTING TESTS PASSED")
