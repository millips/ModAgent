"""Nexus loader/dependency gates run before snapshots and writes."""

import json
import os
import tempfile
import zipfile

data_dir = tempfile.mkdtemp(prefix="ma_preflight_data_")
os.environ["MODAGENT_DATA_DIR"] = data_dir

from modagent import db, tools  # noqa: E402


class Config:
    tier = "pro"
    nexus_api_key = "test"
    tavily_api_key = ""
    game_name = "R.E.P.O."
    game_slug = "repo"
    game_id = 0
    game_root = tempfile.mkdtemp(prefix="ma_preflight_game_")
    game_instance_id = ""
    mod_loader = "BepInEx"
    chrome_cdp_port = 18888


cfg = Config()
db.init_db()
archive = os.path.join(data_dir, "39_MoneyValueTracker.zip")
with zipfile.ZipFile(archive, "w") as handle:
    handle.writestr("MapMoneyMod.dll", b"not-a-real-dll")

old_detail = tools.nexus.get_detail
old_alive = tools.games_mod.verify_game_alive
old_snapshot = tools.snapshot.snapshot_create
snapshot_called = False


def forbidden_snapshot(*_args, **_kwargs):
    global snapshot_called
    snapshot_called = True
    raise AssertionError("snapshot must not run before dependency gate")


tools.nexus.get_detail = lambda *_args, **_kwargs: {
    "mod_id": 39,
    "name": "MoneyValueTracker",
    "dependency_labels": ["RepoLib", "MelonLoader"],
    "required_loader": "MelonLoader",
}
tools.games_mod.verify_game_alive = lambda *_args, **_kwargs: {"alive": True}
tools.snapshot.snapshot_create = forbidden_snapshot

try:
    result = json.loads(tools.execute(
        "mod_install", {
            "mod_id": 39,
            "local_path": archive,
            "require_verified_preflight": True,
        }, cfg
    ))
    assert result["install_blocked"] is True
    assert result["status"] == "dependency_blocked"
    assert result["required_loader"] == "MelonLoader"
    assert result["active_loaders"] == ["BepInEx"]
    assert result["incompatible_loader"] is True
    assert "RepoLib" in result["missing_dependencies"]
    assert snapshot_called is False
    assert not os.path.exists(os.path.join(cfg.game_root, "BepInEx"))
finally:
    tools.nexus.get_detail = old_detail
    tools.games_mod.verify_game_alive = old_alive
    tools.snapshot.snapshot_create = old_snapshot

print("ALL PASS")
