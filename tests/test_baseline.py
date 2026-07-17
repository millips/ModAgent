import os, json, tempfile, types

TMP = tempfile.mkdtemp()

# 隔离:DB 与快照库全部指向临时区,不碰真实数据
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

# ── 造一个"全新 Palworld":有本体 exe,mod 域为空 ──
G = os.path.join(TMP, "Palworld")
EXE = os.path.join(G, "Pal", "Binaries", "Win64", "Palworld-Win64-Shipping.exe")
w(EXE, "EXEDATA")
os.makedirs(os.path.join(G, "Pal", "Content", "Paks"), exist_ok=True)

# 1. 空域 + 活体 → 基线快照
s0 = snap.snapshot_create(G, "palworld", trigger_mod_name="原版基线")
m0 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "palworld", s0, "manifest.json"), encoding="utf-8"))
check("1 baseline created", bool(s0))
check("1 baseline flag + empty files", m0.get("baseline") is True and m0["files"] == [])

# 2. 空域 + 非活体(误配置) → 仍然拒绝
DEAD = os.path.join(TMP, "DeadDir"); os.makedirs(DEAD)
try:
    snap.snapshot_create(DEAD, "palworld")
    check("2 dead dir still raises", False)
except ValueError as e:
    check("2 dead dir still raises", "empty_snapshot" in str(e))

# 3. 装 mod A → 快照 S1
A = os.path.join(G, "Pal", "Content", "Paks", "~mods", "modA_P.pak")
w(A, "AAAA")
s1 = snap.snapshot_create(G, "palworld", trigger_mod_name="装A后")
m1 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "palworld", s1, "manifest.json"), encoding="utf-8"))
check("3 S1 has A", m1["files"] == ["Pal/Content/Paks/~mods/modA_P.pak"] and m1.get("baseline") is False)

# 4. 装 mod B → restore S1 → B 消失、A 完好、exe 未动
B = os.path.join(G, "Pal", "Content", "Paks", "~mods", "modB_P.pak")
w(B, "BBBB")
exe_mtime = os.path.getmtime(EXE)
n = snap.snapshot_restore(s1)
check("4 restore S1: B deleted", not os.path.exists(B))
check("4 restore S1: A intact", os.path.exists(A) and open(A).read() == "AAAA")
check("4 restore S1: exe untouched", os.path.getmtime(EXE) == exe_mtime and open(EXE).read() == "EXEDATA")

# 5. restore 基线 → 域清空回原版,exe 仍未动
w(B, "BBBB")  # 再装回 B,现在域内 A+B
n = snap.snapshot_restore(s0)
check("5 restore baseline: domain emptied", not os.path.exists(A) and not os.path.exists(B))
check("5 restore baseline: exe untouched", open(EXE).read() == "EXEDATA")

# ── 工具层:跨游戏过滤与守卫 ──
from modagent import tools

# 造两个游戏的 DB 记录(快照 s0/s1 已归属 palworld)
db.add_mod(db.InstalledMod(id="m_pal", name="PalMod", version="1", snapshot_id="", game_slug="palworld"))
db.add_mod(db.InstalledMod(id="m_sb", name="SBMod", version="1", snapshot_id="", game_slug="stellarblade"))

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="palworld", game_id=6063,
                            game_root=G, tier="free", chrome_cdp_port=18888)

r = tools.execute("get_installed", {}, cfg)
check("6 get_installed filters by game", "PalMod" in r and "SBMod" not in r and "其他游戏" in r)

r = tools.execute("snapshot_list", {}, cfg)
check("7 snapshot_list filtered + path", s0 in r and s1 in r and "存储于" in r)
check("7 baseline labeled", "原版基线" in r)

# 8. 跨游戏回滚拒绝:把 s1 改挂到 stellarblade 名下再试
conn = db.get_conn(); conn.execute("UPDATE snapshots SET game_slug='stellarblade' WHERE id=?", (s1,)); conn.commit(); conn.close()
r = tools.execute("snapshot_restore", {"snapshot_id": s1}, cfg)
check("8 cross-game restore refused", "跨游戏回滚已拒绝" in r)

# 9. 同游戏回滚仍可用(用 s0)
r = tools.execute("snapshot_restore", {"snapshot_id": s0}, cfg)
check("9 same-game restore works", "files_restored" in r)

print("\nALL PASS" if allok else "\nSOME FAILED")
