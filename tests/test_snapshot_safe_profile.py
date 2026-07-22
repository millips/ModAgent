"""回归：local FF7R 旧版过宽快照不得覆盖游戏原生文件。"""
import json
import os
import shutil
import tempfile
import time

os.environ["MODAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="ma-safe-profile-")

from modagent import db
from modagent import snapshot as snap

db.DB_FILE = os.path.join(os.environ["MODAGENT_DATA_DIR"], "state.db")
db.init_db()
snap.SNAPSHOTS_DIR = os.path.join(os.environ["MODAGENT_DATA_DIR"], "snapshots")

root = os.path.join(os.environ["MODAGENT_DATA_DIR"], "FINAL FANTASY VII REBIRTH")
official = os.path.join(root, "Engine", "Plugins", "Official", "game.dll")
injector = os.path.join(root, "End", "Binaries", "Win64", "xinput1_3.dll")
os.makedirs(os.path.dirname(official), exist_ok=True)
os.makedirs(os.path.dirname(injector), exist_ok=True)
open(official, "w", encoding="utf-8").write("OLD-OFFICIAL")
open(injector, "w", encoding="utf-8").write("HOOK")

sid = "snap_legacy_unsafe"
sdir = os.path.join(snap.SNAPSHOTS_DIR, "local_final_fantasy_vii_rebirth", sid)
os.makedirs(os.path.dirname(os.path.join(sdir, "Engine/Plugins/Official/game.dll")), exist_ok=True)
os.makedirs(os.path.dirname(os.path.join(sdir, "End/Binaries/Win64/xinput1_3.dll")), exist_ok=True)
shutil.copy2(official, os.path.join(sdir, "Engine/Plugins/Official/game.dll"))
shutil.copy2(injector, os.path.join(sdir, "End/Binaries/Win64/xinput1_3.dll"))
manifest = {
    "snapshot_id": sid, "schema": 2, "game_root": root,
    "game_slug": "local_final_fantasy_vii_rebirth",
    "files": ["Engine/Plugins/Official/game.dll", "End/Binaries/Win64/xinput1_3.dll"],
    "workshop": None,
}
open(os.path.join(sdir, "manifest.json"), "w", encoding="utf-8").write(json.dumps(manifest))
db.add_snapshot(db.Snapshot(sid, time.time(), json.dumps(manifest["files"]), "", "legacy", manifest["game_slug"]))

# 模拟游戏平台更新官方 DLL，同时注入器被删：只允许恢复注入器。
open(official, "w", encoding="utf-8").write("NEW-OFFICIAL")
os.remove(injector)
preview = snap.snapshot_restore_preview(sid)
assert preview["domain_sniffed"] is False, preview
assert preview["ignored_unsafe_snapshot_files"] == ["Engine/Plugins/Official/game.dll"], preview
assert preview["to_restore"] == ["End/Binaries/Win64/xinput1_3.dll"], preview

result = snap.snapshot_restore(sid)
assert result["complete"] is True, result
assert open(official, encoding="utf-8").read() == "NEW-OFFICIAL"
assert open(injector, encoding="utf-8").read() == "HOOK"
assert result["files_restored"] == 1 and result["verified_target_files"] == 1, result
print("ALL PASS")
