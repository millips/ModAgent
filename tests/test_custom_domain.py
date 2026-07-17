"""T2 第1块:快照域地基 —— 精确文件 spec + custom_domains 登记。

覆盖:
  A. db 层 custom_domains CRUD(登记幂等/读取/撤销/按游戏隔离)
  B. _iter_domain_files 精确文件形态:只产出登记过且仍存在的文件,不 walk 目录
  C. _auto_detect_specs 并入:无登记时逐字不变;有登记时末尾追加 files 型 spec
  D. 铁律6 顺序自洽:自定义落点(在嗌探目录名之外)装文件 → 建快照 → 回滚能删除新增/还原
  E. 精确性:绝不误纳入同目录下未登记的游戏原文件
"""
import os, json, tempfile, types

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

# ── A. db CRUD ──
db.add_custom_domain_files("g1", ["Cfg/a.ini", "Cfg\\b.ini"])   # 反斜杠应归一化
db.add_custom_domain_files("g1", ["Cfg/a.ini"])                  # 重复登记幂等
db.add_custom_domain_files("g2", ["Other/c.dat"])
check("A1 get returns normalized+dedup", db.get_custom_domain_files("g1") == ["Cfg/a.ini", "Cfg/b.ini"])
check("A2 isolated by game", db.get_custom_domain_files("g2") == ["Other/c.dat"])
check("A3 unknown game empty", db.get_custom_domain_files("nope") == [])
db.remove_custom_domain_files("g1", ["Cfg/a.ini"])
check("A4 remove works", db.get_custom_domain_files("g1") == ["Cfg/b.ini"])
check("A5 empty args no-op", (db.add_custom_domain_files("", ["x"]), db.get_custom_domain_files("")) == (None, []))

# ── B. _iter_domain_files 精确文件形态 ──
G = os.path.join(TMP, "Game")
w(os.path.join(G, "SharedData", "mod.assets"), "M")     # 登记的 custom 文件
w(os.path.join(G, "SharedData", "vanilla.assets"), "V") # 同目录游戏原文件,未登记
spec_files = {"files": ["SharedData/mod.assets", "SharedData/missing.assets"]}
got = sorted(snap._iter_domain_files(G, [spec_files]))
check("B1 yields only existing registered file", got == ["SharedData/mod.assets"],
      f"got {got}")
check("B2 does NOT walk sibling vanilla file", "SharedData/vanilla.assets" not in got)

# ── C. _auto_detect_specs 并入 ──
# palworld 是硬编码域;无登记时 spec 不含 files 型
w(os.path.join(G, "Pal", "Binaries", "Win64", "Palworld-Win64-Shipping.exe"), "EXE")
base_specs = snap._auto_detect_specs(G, "palworld")
check("C1 no custom → no files-spec", all("files" not in s for s in base_specs))
db.add_custom_domain_files("palworld", ["SharedData/mod.assets"])
with_custom = snap._auto_detect_specs(G, "palworld")
files_specs = [s for s in with_custom if "files" in s]
check("C2 registered → files-spec appended", len(files_specs) == 1
      and files_specs[0]["files"] == ["SharedData/mod.assets"])
check("C3 dir-specs unchanged", [s for s in with_custom if "dir" in s] == base_specs)

# ── D. 铁律6 顺序自洽 ──
# 关键约束(本测试暴露):custom 落点登记必须在建【安装前快照之前】。否则覆盖游戏原文件时,
# 原文件不在快照域 → 安装前快照没保存它 → 回滚把 mod 文件当"新增物"删除、原文件一并丢失。
# 正确编排 = ①先登记域 ②建安装前快照(原文件入快照受保护)③落位。tools 层须照此序。
db2dir = os.path.join(TMP, "state2.db")
db.DB_FILE = db2dir; db.init_db()
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snap2")

GP = os.path.join(TMP, "Phasmo")
# 活体检测认 *-Shipping.exe 或 >20MB 主 exe;恐鬼症是普通 exe 名,用稀疏文件造 21MB
_exe = os.path.join(GP, "Phasmophobia.exe")
os.makedirs(GP, exist_ok=True)
with open(_exe, "wb") as _f:
    _f.seek(21 * 1024 * 1024); _f.write(b"\0")

# 子场景1【覆盖游戏原文件】:sharedassets 替换类(Ghost Busters Radio 即此类)
COVER_REL = "Phasmophobia_Data/sharedassets2.assets"
COVER = os.path.join(GP, COVER_REL.replace("/", os.sep))
w(COVER, "ORIGINAL")                                        # 游戏原版自带
db.add_custom_domain_files("phasmophobia", [COVER_REL])     # ① 先登记
s1 = snap.snapshot_create(GP, "phasmophobia", trigger_mod_name="装前")  # ② 安装前快照
m1 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "phasmophobia", s1, "manifest.json"), encoding="utf-8"))
check("D1 先登记→游戏原文件入安装前快照(受保护)", COVER_REL in m1["files"])
w(COVER, "MODDED")                                          # ③ 落位覆盖
res = snap.snapshot_restore(s1)
check("D2 覆盖类回滚→还原游戏原文件", open(COVER).read() == "ORIGINAL",
      f"content={open(COVER).read()!r}")

# 子场景2【新增全新文件】:落点原本无文件
NEW_REL = "Phasmophobia_Data/newmod.bundle"
NEW = os.path.join(GP, NEW_REL.replace("/", os.sep))
db.add_custom_domain_files("phasmophobia", [NEW_REL])       # ① 登记(原位置尚无文件)
s2 = snap.snapshot_create(GP, "phasmophobia", trigger_mod_name="装前2")  # ②
m2 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "phasmophobia", s2, "manifest.json"), encoding="utf-8"))
check("D3 新增类:落点无文件→不入快照", NEW_REL not in m2["files"])
w(NEW, "BRANDNEW")                                          # ③ 落位新建
res = snap.snapshot_restore(s2)
check("D4 新增类回滚→删除新增文件", not os.path.exists(NEW))

# 反向:装后快照能还原被删的 custom 文件
w(NEW, "BRANDNEW")
s3 = snap.snapshot_create(GP, "phasmophobia", trigger_mod_name="装后")
os.remove(NEW)
res = snap.snapshot_restore(s3)
check("D5 装后快照回滚→重建被删 custom 文件", os.path.exists(NEW) and open(NEW).read() == "BRANDNEW")

# ── E. 精确性:同目录未登记文件绝不被回滚删除 ──
SIBLING = os.path.join(GP, "Phasmophobia_Data", "level0")   # 游戏原文件,同目录,未登记
w(SIBLING, "GAMELEVEL")
w(NEW, "BRANDNEW")
res = snap.snapshot_restore(s3)                            # s3 域含 NEW,但绝不含未登记的 SIBLING
check("E1 未登记的同目录游戏原文件不受回滚影响",
      os.path.exists(SIBLING) and open(SIBLING).read() == "GAMELEVEL")

print("\nALL PASS" if allok else "\nSOME FAILED")
