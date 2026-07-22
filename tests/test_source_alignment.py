import json
import os
import tempfile
import types

import modagent.config as config


TMP = tempfile.mkdtemp()
config.CONFIG_DIR = os.path.join(TMP, "cfg")
os.makedirs(config.CONFIG_DIR, exist_ok=True)

from modagent import db, source_alignment, tools
from modagent.agent import collapse_repeated_response
from modagent.report_validator import check_unfulfilled_action_promise
from modagent.sources import thunderstore


db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()


def add(mid, name, version="unknown", files=None):
    db.add_mod(db.InstalledMod(
        id=mid,
        name=name,
        version=version,
        snapshot_id="",
        files_installed=json.dumps(files or []),
        installed_by="imported",
        game_slug="repo",
    ))


add("local_repolib", "REPOLib")
add("local_pickup", "PickupSound", "1.0.3")
add("local_map", "Map Value Tracker Plus", "1.0.3")

packages = [
    {
        "name": "REPOLib",
        "owner": "Zehs",
        "full_name": "Zehs-REPOLib",
        "package_url": "https://thunderstore.io/c/repo/p/Zehs/REPOLib/",
        "versions": [{"version_number": "4.2.0", "description": "library", "downloads": 10}],
    },
    {
        "name": "PickupSound",
        "owner": "nickklmao",
        "full_name": "nickklmao-PickupSound",
        "package_url": "https://thunderstore.io/c/repo/p/nickklmao/PickupSound/",
        "versions": [{"version_number": "1.0.4", "description": "sound", "downloads": 5}],
    },
    {
        "name": "MapValueTracker",
        "owner": "Tansinator",
        "full_name": "Tansinator-MapValueTracker",
        "package_url": "https://thunderstore.io/c/repo/p/Tansinator/MapValueTracker/",
        "versions": [{"version_number": "1.3.0", "description": "map", "downloads": 8}],
    },
]

old_find = thunderstore.find_community
old_list = thunderstore.list_packages
thunderstore.find_community = lambda _name: "repo"
thunderstore.list_packages = lambda _community, force_refresh=False: packages

cfg = types.SimpleNamespace(
    game_name="R.E.P.O.", game_slug="repo", game_id=0, game_root=TMP,
    nexus_api_key="", tier="subscription", chrome_cdp_port=18888,
)
try:
    aligned = source_alignment.align_installed_mods(cfg)
    bound_ids = {item["mod_id"] for item in aligned["bound"]}
    assert {"local_repolib", "local_pickup"} <= bound_ids
    assert db.get_mod_source_binding("local_repolib", "repo")["source_key"] == "Zehs-REPOLib"
    assert db.get_mod_source_binding("local_pickup", "repo")["latest_version"] == "1.0.4"

    checked = json.loads(tools.execute("mod_update_check", {}, cfg))
    by_id = {item["mod_id"]: item for item in checked["items"]}
    assert by_id["local_repolib"]["status"] == "version_unknown"
    assert by_id["local_repolib"]["can_update"] is True
    assert by_id["local_pickup"]["status"] == "update_available"
    assert any(item["mod_id"] == "local_pickup" for item in checked["updates_available"])
finally:
    thunderstore.find_community = old_find
    thunderstore.list_packages = old_list


promise = "数据够了。我来手动帮你查最新情况——先搜索 Thunderstore。"
assert check_unfulfilled_action_promise(promise) is True
assert check_unfulfilled_action_promise("你确认后，我会更新这三个 Mod。") is False

block = "这是完整结论。\n\n- A：已经成功取得真实来源和版本信息。\n- B：已经成功取得真实来源和版本信息。"
assert collapse_repeated_response(block + "\n" + block) == block

print("ALL PASS")
