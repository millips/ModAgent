"""A failed Mod update automatically restores its pre-update snapshot."""
import json
import os
import tempfile
import types

import modagent.config as config


TMP = tempfile.mkdtemp()
config.CONFIG_DIR = os.path.join(TMP, "cfg")
os.makedirs(config.CONFIG_DIR, exist_ok=True)

import modagent.db as db
from modagent import tools


db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()
db.add_mod(db.InstalledMod(
    id="10", name="Rollback Target", version="1.0", snapshot_id="old-snapshot",
    files_installed=json.dumps([os.path.join(TMP, "old.pak")]), game_slug="repo",
))

cfg = types.SimpleNamespace(
    nexus_api_key="key", game_slug="repo", game_id=1, game_root=TMP,
    tier="free", chrome_cdp_port=18888,
)

originals = {
    "get_main_file": tools.nexus.get_main_file,
    "download_mod": tools.downloader.download_mod,
    "snapshot_create": tools.snapshot.snapshot_create,
    "snapshot_restore": tools.snapshot.snapshot_restore,
    "uninstall_mod": tools.installer.uninstall_mod,
    "install_mod": tools.installer.install_mod,
}


async def fake_download_mod(**kwargs):
    archive = os.path.join(TMP, "new.zip")
    with open(archive, "wb") as handle:
        handle.write(b"test archive")
    return {"local_path": archive}


tools.nexus.get_main_file = lambda *args, **kwargs: {"file_id": 20, "version": "2.0"}
tools.downloader.download_mod = fake_download_mod
tools.snapshot.snapshot_create = lambda *args, **kwargs: "update-snapshot"
tools.snapshot.snapshot_restore = lambda sid: {
    "complete": True, "deleted": 1, "restored": 1,
    "failed": {"delete": [], "restore": []}
}
tools.installer.uninstall_mod = lambda *args, **kwargs: {"removed": ["old.pak"], "errors": []}
tools.installer.install_mod = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broken archive"))

try:
    result = json.loads(tools.execute("mod_update", {"mod_id": "10"}, cfg))
finally:
    tools.nexus.get_main_file = originals["get_main_file"]
    tools.downloader.download_mod = originals["download_mod"]
    tools.snapshot.snapshot_create = originals["snapshot_create"]
    tools.snapshot.snapshot_restore = originals["snapshot_restore"]
    tools.installer.uninstall_mod = originals["uninstall_mod"]
    tools.installer.install_mod = originals["install_mod"]

assert "error" in result
assert result["restored_previous"] is True
assert result["snapshot_id"] == "update-snapshot"
assert db.get_mod("10", "repo").version == "1.0"

print("ALL PASS")
