"""战役 1(v1.0):回滚预览 + 开放模式强制确认 + 失败记账。

覆盖:
  A. snapshot_restore_preview 干跑正确性(将删除/将还原/未变动/快照缺失),且绝不落盘
  B. 预览 == 执行(同一份 plan,预览说什么执行就做什么)
  C. 工具层确认门:嗅探域游戏不带 confirmed → 返回预览拒绝执行;带 confirmed → 执行
  D. 硬编码域游戏(palworld)不受门影响,一次调用直达
  E. 文件被占用时失败入账(failed 分桶 + warning),不再静默吞 OSError
"""
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

# ── 造一个嗅探域游戏(testgame 不在 GAME_SNAPSHOT_SPECS)──
G = os.path.join(TMP, "Game")
w(os.path.join(G, "Game-Win64-Shipping.exe"), "EXE")
A = os.path.join(G, "BepInEx", "plugins", "modA.dll"); w(A, "AAAA")
C = os.path.join(G, "BepInEx", "plugins", "modC.dll"); w(C, "CCCC")

s1 = snap.snapshot_create(G, "testgame", trigger_mod_name="A+C 在位")

# 快照后:装 B(将删除)、改 A 内容(将还原)、C 不动(未变动)
B = os.path.join(G, "BepInEx", "plugins", "modB.dll"); w(B, "BBBB")
w(A, "AAAA-tampered-longer")           # size 变 → _same_file 判不同

# ── A. 预览干跑正确性 ──
pv = snap.snapshot_restore_preview(s1)
check("A1 to_delete = [B]", pv["to_delete"] == ["BepInEx/plugins/modB.dll"]
      and pv["to_delete_count"] == 1, f"got {pv['to_delete']}")
check("A2 to_restore = [A]", pv["to_restore"] == ["BepInEx/plugins/modA.dll"]
      and pv["to_restore_count"] == 1, f"got {pv['to_restore']}")
check("A3 unchanged = 1 (C)", pv["unchanged_count"] == 1)
check("A4 domain_sniffed flagged", pv["domain_sniffed"] is True)
check("A5 not baseline", pv["baseline"] is False)
check("A6 dry-run: disk untouched", os.path.exists(B)
      and open(A).read() == "AAAA-tampered-longer")

# 快照残缺如实报:从快照目录里抽走 C
snap_c = os.path.join(snap.SNAPSHOTS_DIR, "testgame", s1, "BepInEx", "plugins", "modC.dll")
os.remove(snap_c)
pv2 = snap.snapshot_restore_preview(s1)
check("A7 missing_in_snapshot reported", pv2["missing_in_snapshot"] == ["BepInEx/plugins/modC.dll"])
# C 在游戏侧还在,unchanged 里没了它;还原它已不可能,预览不许谎报
check("A8 missing not promised in to_restore", "BepInEx/plugins/modC.dll" not in pv2["to_restore"])

# ── C. 工具层确认门(嗅探域)──
cfg = types.SimpleNamespace(nexus_api_key="", game_slug="testgame", game_id=0,
                            game_root=G, tier="free", chrome_cdp_port=18888)
r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s1}, cfg))
check("C1 unconfirmed → requires_confirmation", r.get("requires_confirmation") is True
      and "preview" in r and "note" in r)
check("C2 gate did not touch disk", os.path.exists(B)
      and open(A).read() == "AAAA-tampered-longer")
check("C3 gate preview carries lists", r["preview"]["to_delete"] == ["BepInEx/plugins/modB.dll"])

# ── B+C. 带 confirmed 执行,且结果与预览一致 ──
r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s1, "confirmed": True}, cfg))
check("B1 executed: deleted==preview", r["deleted"] == pv2["to_delete_count"] == 1
      and not os.path.exists(B))
check("B2 executed: restored==preview", r["restored"] == pv2["to_restore_count"] == 1
      and open(A).read() == "AAAA")
check("B3 files_restored compat = deleted+restored", r["files_restored"] == 2)
check("B4 missing file skipped, no failure charged", "failed" not in r,
      f"failed={r.get('failed')}")

# ── D. 硬编码域游戏不设门:palworld 一次调用直达 ──
GP = os.path.join(TMP, "Palworld")
w(os.path.join(GP, "Pal", "Binaries", "Win64", "Palworld-Win64-Shipping.exe"), "EXE")
PA = os.path.join(GP, "Pal", "Content", "Paks", "~mods", "modA_P.pak"); w(PA, "AAAA")
sp = snap.snapshot_create(GP, "palworld", trigger_mod_name="装A后")
PB = os.path.join(GP, "Pal", "Content", "Paks", "~mods", "modB_P.pak"); w(PB, "BBBB")
cfgp = types.SimpleNamespace(nexus_api_key="", game_slug="palworld", game_id=6063,
                             game_root=GP, tier="free", chrome_cdp_port=18888)
r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": sp}, cfgp))
check("D1 curated domain: no gate, executed", "requires_confirmation" not in r
      and r["deleted"] == 1 and not os.path.exists(PB))

# ── E. 失败记账:文件被占用(Windows 下打开即锁删除)──
w(PB, "BBBB")
fh = open(PB, "r")                     # 持有句柄 → os.remove 得 PermissionError(OSError 子类)
try:
    res = snap.snapshot_restore(sp)
finally:
    fh.close()
# 战役3:failed 项升级为带 errno 归因的 {rel, code, reason, action}
_fd = res["failed"]["delete"]
locked_ok = (res["deleted"] == 0 and len(_fd) == 1
             and _fd[0]["rel"] == "Pal/Content/Paks/~mods/modB_P.pak"
             and _fd[0]["code"] in ("locked", "permission")
             and _fd[0]["action"].strip())
check("E1 locked file charged to failed.delete + classified", locked_ok,
      f"res={ {k: res[k] for k in ('deleted','restored','failed')} }")
# 工具层把失败翻译成 warning(游戏在跑的提示)
w(PB, "BBBB")
fh = open(PB, "r")
try:
    r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": sp}, cfgp))
finally:
    fh.close()
check("E2 tool surfaces warning", "warning" in r and r["failed"]["delete"], f"got {r}")
os.remove(PB)   # 收尾

# ── 基线快照的预览语义 ──
pvb = None
GB = os.path.join(TMP, "Fresh")
w(os.path.join(GB, "Pal", "Binaries", "Win64", "Fresh-Win64-Shipping.exe"), "EXE")
os.makedirs(os.path.join(GB, "Pal", "Content", "Paks"), exist_ok=True)
sb = snap.snapshot_create(GB, "palworld", trigger_mod_name="原版基线")
w(os.path.join(GB, "Pal", "Content", "Paks", "~mods", "x.pak"), "X")
pvb = snap.snapshot_restore_preview(sb)
check("F1 baseline preview: delete-all semantics", pvb["baseline"] is True
      and pvb["to_delete"] == ["Pal/Content/Paks/~mods/x.pak"] and pvb["to_restore_count"] == 0)

print("\nALL PASS" if allok else "\nSOME FAILED")
