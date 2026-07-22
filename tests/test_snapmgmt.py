import os, json, tempfile, types, time

TMP = tempfile.mkdtemp()

import modagent.db as db
db.DB_FILE = os.path.join(TMP, "test_state.db")
db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# 造活体游戏
G = os.path.join(TMP, "Game")
w(os.path.join(G, "Game-Win64-Shipping.exe"), "EXE")
MODS = os.path.join(G, "BepInEx", "plugins")
os.makedirs(MODS)

# 1. snapshot_delete:目录 + DB 一起清
w(os.path.join(MODS, "a.dll"), "A")
s1 = snap.snapshot_create(G, "testgame", trigger_mod_name="s1")
d1 = os.path.join(snap.SNAPSHOTS_DIR, "testgame", s1)
r = snap.snapshot_delete(s1)
check("1 delete removes dir+db", not os.path.isdir(d1) and db.get_snapshot(s1) is None and r["deleted"] == s1)

# 2. 删不存在的 → FileNotFoundError
try:
    snap.snapshot_delete("snap_nope")
    check("2 missing raises", False)
except FileNotFoundError:
    check("2 missing raises", True)

# 3. 保留策略:造 1 基线 + 24 普通(直接写 DB 行,磁盘只造目录) → prune 后 20 条,基线保留
conn = db.get_conn()
conn.execute("DELETE FROM snapshots"); conn.commit(); conn.close()
ids = []
for i in range(25):
    sid = f"snap_fake_{i:03d}"
    ids.append(sid)
    files = "[]" if i == 0 else json.dumps([f"BepInEx/plugins/m{i}.dll"])
    db.add_snapshot(db.Snapshot(id=sid, timestamp=1000.0 + i, files=files,
                                trigger_mod_id="", trigger_mod_name=f"t{i}", game_slug="testgame"))
    os.makedirs(os.path.join(snap.SNAPSHOTS_DIR, "testgame", sid), exist_ok=True)
    w(os.path.join(snap.SNAPSHOTS_DIR, "testgame", sid, "manifest.json"), "{}")
pruned = snap._prune_old_snapshots("testgame")
left = [s.id for s in db.list_snapshots("testgame")]
check("3 pruned to MAX", len(left) == snap.MAX_SNAPSHOTS, f"left={len(left)}")
check("3 baseline survives", "snap_fake_000" in left)
check("3 oldest non-baseline pruned first", "snap_fake_001" in pruned and "snap_fake_024" not in pruned)

# 4. 工具层跨游戏删除守卫
from modagent import tools
cfg = types.SimpleNamespace(nexus_api_key="", game_slug="othergame", game_id=0,
                            game_root=G, tier="free", chrome_cdp_port=18888)
r = json.loads(tools.execute("snapshot_delete", {"snapshot_id": "snap_fake_024"}, cfg))
check("4 cross-game delete refused", "跨游戏删除已拒绝" in r.get("error", ""))

cfg.game_slug = "testgame"
r = json.loads(tools.execute("snapshot_delete", {"snapshot_id": "snap_fake_024"}, cfg))
check("4 same-game delete requires confirmation", r.get("requires_confirmation") is True)
token = r.get("confirmation_token", "")
denied = json.loads(tools.execute("snapshot_delete", {
    "snapshot_id": "snap_fake_024", "confirmed": True, "confirmation_token": "bad",
}, cfg))
check("4 invalid token refused", denied.get("error") == "snapshot_delete_confirmation_invalid")
r = json.loads(tools.execute("snapshot_delete", {
    "snapshot_id": "snap_fake_024", "confirmed": True, "confirmation_token": token,
}, cfg))
check("4 confirmed same-game delete ok", r.get("deleted") == "snap_fake_024")

print("\nALL PASS" if allok else "\nSOME FAILED")
