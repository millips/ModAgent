"""公开包回归：FF7R 本地/Nexus 身份贯通、自动安装、重复下载短路。"""
import json
import os
import tempfile
import types
import zipfile

tmp = tempfile.mkdtemp(prefix="ma-ff7-public-")
os.environ["MODAGENT_DATA_DIR"] = os.path.join(tmp, "data")

from modagent import db, downloader, installer, tools
from modagent.agent import Agent

db.DB_FILE = os.path.join(tmp, "state.db")
db.init_db()
downloader.DOWNLOADS_DIR = os.path.join(tmp, "downloads")
downloader.DROPBOX_DIR = os.path.join(tmp, "dropbox")
installer.BACKUPS_DIR = os.path.join(tmp, "backups")

game = os.path.join(tmp, "FINAL FANTASY VII REBIRTH")
os.makedirs(os.path.join(game, "End", "Binaries", "Win64"), exist_ok=True)
open(os.path.join(game, "End", "Binaries", "Win64", "ff7rebirth_.exe"), "wb").write(b"MZ" + b"0" * 1024)

def make_zip(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)

# 1. Dresscode/Reunion 风格插件目录保持结构进 End/Mods。
plugin = os.path.join(tmp, "plugin.zip")
make_zip(plugin, {
    "Yuffie_Cowgirl/Yuffie_Cowgirl.uplugin": "{}",
    "Yuffie_Cowgirl/Content/Paks/WindowsNoEditor/Yuffie.pak": "pak",
    "Yuffie_Cowgirl/Resources/Icon128.png": "png",
})
r = installer.install_mod(plugin, game, "local_final_fantasy_vii_rebirth")
assert len(r["installed"]) == 3, r
assert os.path.isfile(os.path.join(game, "End", "Mods", "Yuffie_Cowgirl", "Yuffie_Cowgirl.uplugin"))
assert os.path.isfile(os.path.join(game, "End", "Mods", "Yuffie_Cowgirl", "Content", "Paks", "WindowsNoEditor", "Yuffie.pak"))

# 2. FFVIIHook 注入器自动落到 Win64；松散 pak 自动落 ~mods。
hook = os.path.join(tmp, "hook.zip")
make_zip(hook, {"xinput1_3.dll": "hook", "README.txt": "docs"})
r = installer.install_mod(hook, game, "local_final_fantasy_vii_rebirth")
assert len(r["installed"]) == 1 and r["skipped"] == ["README.txt"], r
assert os.path.isfile(os.path.join(game, "End", "Binaries", "Win64", "xinput1_3.dll"))

# 3. 指定 file_id 的同一文件命中持久缓存，不会重复下载。
bucket = os.path.join(downloader.DOWNLOADS_DIR, "finalfantasy7rebirth")
cached = os.path.join(bucket, "1061_Reunion_Mod_Loader_v1.2.0.zip")
make_zip(cached, {"FF7RML/FF7RML.uplugin": "{}"})
downloader._remember_download(cached, "finalfantasy7rebirth", 1061, 6212)
assert downloader.find_cached_nexus_download("finalfantasy7rebirth", 1061, 6212) == cached
assert downloader.find_cached_nexus_download("finalfantasy7rebirth", 1061, 9999) == ""

# 4. 本地 slug 的缓存列表能看到 Nexus slug 桶，mod_install 能直接消费。
tools.nexus.discover_game = lambda *a, **k: {
    "status": "available", "slug": "finalfantasy7rebirth", "game_id": 7237,
}
tools.games_mod.verify_game_alive = lambda root: {"alive": True}
cfg = types.SimpleNamespace(
    nexus_api_key="", tavily_api_key="", game_name="FINAL FANTASY VII REBIRTH",
    game_slug="local_final_fantasy_vii_rebirth", game_id=0, game_root=game,
    tier="subscription", chrome_cdp_port=18888, manual_mod_dirs={},
)
listed = json.loads(tools.execute("list_downloads", {}, cfg))
assert listed["count"] == 1 and listed["files"][0]["cache_bucket"] == "finalfantasy7rebirth", listed
installed = json.loads(tools.execute("mod_install", {"mod_id": 1061, "snapshot_id": "test"}, cfg))
assert installed.get("files_installed"), installed
assert not os.path.exists(cached), "successful install must clean archive"

# 5. 安装确认不能被模型擅自转成卸载确认。
agent = Agent(cfg)
agent._current_user_msg = "确认安装这四个 Mod"
agent._prior_assistant_text = "是否开始下载安装？"
blocked = json.loads(agent._exec("mod_uninstall", {"mod_id": "1061", "confirmed": True}))
assert blocked["error"] == "confirmation_intent_mismatch", blocked

print("FF7R PUBLIC FLOW TESTS PASSED")
