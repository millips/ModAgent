"""卸载确认门:mod_uninstall 不带 confirmed 先返回预览、不动磁盘;带 confirmed 才执行。"""
import os, json, tempfile, types

TMP = tempfile.mkdtemp()
import modagent.config as config
config.CONFIG_DIR = os.path.join(TMP, "cfg"); os.makedirs(config.CONFIG_DIR, exist_ok=True)
import importlib
import modagent.db as db
db.DB_FILE = os.path.join(TMP, "state.db"); db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")
import modagent.installer as installer; importlib.reload(installer)
from modagent import tools

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# 游戏(活体)+ 已装 mod A(2 文件)+ mod B 依赖 A
G = os.path.join(TMP, "Game")
w(os.path.join(G, "Game-Win64-Shipping.exe"), "EXE")
A1 = os.path.join(G, "BepInEx", "plugins", "modA.dll"); w(A1, "A1")
A2 = os.path.join(G, "BepInEx", "plugins", "modA.cfg"); w(A2, "A2")
db.add_mod(db.InstalledMod(id="modA", name="Mod A", version="1", snapshot_id="",
                           files_installed=json.dumps([A1, A2]), game_slug="repo"))
db.add_mod(db.InstalledMod(id="modB", name="Mod B", version="1", snapshot_id="",
                           dependencies=json.dumps(["modA"]), game_slug="repo"))

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="repo", game_id=0,
                            game_root=G, tier="free", chrome_cdp_port=18888)

# ── 不带 confirmed → 预览,磁盘/DB 不动 ──
r = json.loads(tools.execute("mod_uninstall", {"mod_id": "modA"}, cfg))
check("A1 requires_confirmation", r.get("requires_confirmation") is True)
check("A2 preview: will delete 2", r["will_delete_count"] == 2 and len(r["will_delete_sample"]) == 2)
check("A3 preview: not workshop", r["will_unsubscribe"] is False and r["kind"] == "本地文件")
check("A4 preview: dependents warned", r["dependents"] == ["Mod B"] and "依赖" in r["note"])
check("A5 gate did NOT touch disk", os.path.exists(A1) and os.path.exists(A2))
check("A6 gate did NOT remove DB row", db.get_mod("modA") is not None)
snaps_before = len(db.list_snapshots("repo"))
check("A7 gate did NOT create snapshot", snaps_before == 0)

# ── 带 confirmed → 真执行 ──
r = json.loads(tools.execute("mod_uninstall", {"mod_id": "modA", "confirmed": True}, cfg))
check("B1 executed: removed 2", r.get("removed") == 2)
check("B2 files gone", not os.path.exists(A1) and not os.path.exists(A2))
check("B3 DB row removed", db.get_mod("modA") is None)
check("B4 snapshot created before uninstall", len(db.list_snapshots("repo")) == 1)
check("B5 dependents surfaced in result", r.get("dependents_warned") == ["Mod B"])

# ── 工坊 mod:不带 confirmed 也要预览(退订是破坏性)──
db.add_mod(db.InstalledMod(id="ws_999", name="Workshop 999", version="", snapshot_id="",
                           installed_by="steam_workshop", game_slug="repo"))
r = json.loads(tools.execute("mod_uninstall", {"mod_id": "ws_999"}, cfg))
check("C1 workshop requires_confirmation", r.get("requires_confirmation") is True
      and r["will_unsubscribe"] is True and "退订" in r["kind"])
check("C2 workshop still subscribed (not touched)", db.get_mod("ws_999") is not None)

print("\nALL PASS" if allok else "\nSOME FAILED")
