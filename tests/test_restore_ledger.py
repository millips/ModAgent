import os, json, tempfile, types

TMP = tempfile.mkdtemp()

import modagent.db as db
db.DB_FILE = os.path.join(TMP, "test_state.db")
db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")
from modagent import tools

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# 游戏:活体 + mod A 已装 + mod D 已装但快照前就被禁用(.disabled 进快照)
G = os.path.join(TMP, "Game")
w(os.path.join(G, "Game-Win64-Shipping.exe"), "EXE")
A = os.path.join(G, "BepInEx", "plugins", "modA.dll"); w(A, "A")
db.add_mod(db.InstalledMod(id="modA", name="Mod A", version="1", snapshot_id="",
                           files_installed=json.dumps([A]), game_slug="testgame"))
D = os.path.join(G, "BepInEx", "plugins", "modD.dll")
w(D + ".disabled", "D")   # 禁用状态入快照
db.add_mod(db.InstalledMod(id="modD", name="Mod D", version="1", snapshot_id="",
                           files_installed=json.dumps([D]), game_slug="testgame"))

s1 = snap.snapshot_create(G, "testgame", trigger_mod_name="有A+禁用D")

# 快照后:装 B(文件+记录)、装 C 后禁用(文件改名 .disabled)、一条工坊记录
B = os.path.join(G, "BepInEx", "plugins", "modB.dll"); w(B, "B")
db.add_mod(db.InstalledMod(id="modB", name="Mod B", version="1", snapshot_id="",
                           files_installed=json.dumps([B]), game_slug="testgame"))
C = os.path.join(G, "BepInEx", "plugins", "modC.dll"); w(C, "C")
os.rename(C, C + ".disabled")
db.add_mod(db.InstalledMod(id="modC", name="Mod C", version="1", snapshot_id="",
                           files_installed=json.dumps([C]), game_slug="testgame"))
db.add_mod(db.InstalledMod(id="ws_999", name="Workshop 999", version="", snapshot_id="",
                           installed_by="steam_workshop",
                           files_installed=json.dumps([os.path.join(TMP, "nowhere.pak")]),
                           game_slug="testgame"))

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="testgame", game_id=0,
                            game_root=G, tier="free", chrome_cdp_port=18888)
# testgame 是嗅探域(开放模式),工具层强制预览确认 → 带 confirmed 直达执行
# (不带 confirmed 的门本身由 test_restore_preview.py 覆盖)
r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s1, "confirmed": True}, cfg))

check("1 B file rolled back", not os.path.exists(B))
check("1 B ghost record cleaned", db.get_mod("modB") is None
      and any(m["id"] == "modB" for m in r["mods_cleaned"]))
check("2 A intact (file+record)", os.path.exists(A) and db.get_mod("modA") is not None)
check("3 post-snapshot disabled C correctly removed (file+record)",
      not os.path.exists(C + ".disabled") and db.get_mod("modC") is None)
check("3b pre-snapshot disabled D survives (guard works)",
      os.path.exists(D + ".disabled") and db.get_mod("modD") is not None,
      f"mods_cleaned={r['mods_cleaned']}")
check("4 workshop record untouched by this path", db.get_mod("ws_999") is not None)

print("\nALL PASS" if allok else "\nSOME FAILED")
