"""T2 第2块:installer.install_mod_custom — 显式 mapping 落位 + 三层校验。

覆盖:
  A. 正常落位:新增 + 覆盖(覆盖前备份到集中区,overwrote 标记正确)
  B. 硬拒绝:绝对路径 / 含 .. / 越出 game_root(commonpath 守卫)
  C. 源不存在 → skip
  D. 软告警放行:覆盖已有文件、可执行文件落游戏根 —— 记 warning 但仍安装
  E. rel 字段(相对 game_root 正斜杠)正确 —— 供第3块登记进快照域
  F. 单层壳目录剥离,mapping 用剥壳后路径(与 conflict_check 对齐)
"""
import os, sys, json, tempfile, zipfile

TMP = tempfile.mkdtemp()

import modagent.config as config
config.CONFIG_DIR = os.path.join(TMP, "cfgdir")   # 隔离备份集中区(~/.modagent/backups)
os.makedirs(config.CONFIG_DIR, exist_ok=True)
import importlib
import modagent.installer as installer
importlib.reload(installer)   # 让 BACKUPS_DIR 吃到隔离后的 CONFIG_DIR

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def make_zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

G = os.path.join(TMP, "Game")
os.makedirs(G, exist_ok=True)

# ── A/D/E. 正常落位 + 覆盖 + rel ──
zip1 = os.path.join(TMP, "mod1.zip")
make_zip(zip1, {
    "sharedassets2.assets": "MODDED",     # 覆盖游戏原文件
    "readme.txt": "install to _Data",     # 会被映射(测试任意落点)
    "winhttp.dll": "INJECTOR",            # 可执行文件落游戏根 → 软告警
})
w(os.path.join(G, "Phasmophobia_Data", "sharedassets2.assets"), "ORIGINAL")   # 预置原文件

mapping1 = {
    "sharedassets2.assets": "Phasmophobia_Data/sharedassets2.assets",  # 覆盖
    "readme.txt": "Phasmophobia_Data/docs/readme.txt",                 # 新增
    "winhttp.dll": "winhttp.dll",                                      # 落根,可执行
}
r = installer.install_mod_custom(zip1, G, "phasmophobia", mapping1)
inst_by_rel = {i["rel"]: i for i in r["installed"]}
check("A1 three files installed", len(r["installed"]) == 3, f"got {len(r['installed'])}")
check("A2 overwrite applied", open(os.path.join(G, "Phasmophobia_Data", "sharedassets2.assets")).read() == "MODDED")
check("A3 new file created", os.path.exists(os.path.join(G, "Phasmophobia_Data", "docs", "readme.txt")))
check("E1 rel is game-relative fwd-slash",
      "Phasmophobia_Data/sharedassets2.assets" in inst_by_rel
      and "Phasmophobia_Data/docs/readme.txt" in inst_by_rel)
check("D1 overwrote flag correct",
      inst_by_rel["Phasmophobia_Data/sharedassets2.assets"]["overwrote"] is True
      and inst_by_rel["Phasmophobia_Data/docs/readme.txt"]["overwrote"] is False)
check("D2 overwrite warning present", any("覆盖已存在文件" in w for w in r["warnings"]))
check("D3 root-exec warning present", any("可执行文件落游戏根" in w for w in r["warnings"]))
# 覆盖前备份进集中区(C-0)
bak = os.path.join(installer.BACKUPS_DIR, "phasmophobia", "Phasmophobia_Data", "sharedassets2.assets")
check("A4 original backed up to central区", os.path.exists(bak) and open(bak).read() == "ORIGINAL",
      f"bak={bak}")

# ── B. 硬拒绝:绝对路径 / .. / 越界 ──
zip2 = os.path.join(TMP, "mod2.zip")
make_zip(zip2, {"a.txt": "A", "b.txt": "B", "c.txt": "C"})
outside = os.path.join(TMP, "OUTSIDE")   # 游戏目录之外
mapping2 = {
    "a.txt": os.path.join(outside, "evil.txt"),   # 绝对路径 → 拒
    "b.txt": "../OUTSIDE/evil2.txt",               # .. 逃逸 → 拒
    "c.txt": "safe/c.txt",                         # 合法
}
r2 = installer.install_mod_custom(zip2, G, "phasmophobia", mapping2)
skipped_srcs = {s["src"] for s in r2["skipped"]}
check("B1 absolute path rejected", "a.txt" in skipped_srcs)
check("B2 dotdot escape rejected", "b.txt" in skipped_srcs)
check("B3 legit file installed", any(i["src"] == "c.txt" for i in r2["installed"])
      and os.path.exists(os.path.join(G, "safe", "c.txt")))
check("B4 nothing escaped game_root", not os.path.exists(os.path.join(outside, "evil.txt"))
      and not os.path.exists(os.path.join(TMP, "OUTSIDE", "evil2.txt")))

# ── C. 源不存在 → skip ──
r3 = installer.install_mod_custom(zip2, G, "phasmophobia", {"nope.txt": "Data/nope.txt"})
check("C1 missing source skipped", len(r3["installed"]) == 0
      and any(s["src"] == "nope.txt" and "不存在" in s["reason"] for s in r3["skipped"]))

# ── F. 单层壳目录剥离(与 conflict_check 对齐)──
zip4 = os.path.join(TMP, "mod4.zip")
make_zip(zip4, {"GhostRadio_v1.2/audio.bank": "BANK"})   # 版本号壳目录
# mapping 用剥壳后的路径(agent 看到的 conflict_check archive_contents 就是剥壳后的)
r4 = installer.install_mod_custom(zip4, G, "phasmophobia", {"audio.bank": "Phasmophobia_Data/audio.bank"})
check("F1 wrapper dir stripped, mapping matches",
      any(i["src"] == "audio.bank" for i in r4["installed"])
      and os.path.exists(os.path.join(G, "Phasmophobia_Data", "audio.bank")))

# ── 空 mapping 防御 ──
r5 = installer.install_mod_custom(zip2, G, "phasmophobia", {})
check("G1 empty mapping no-op", len(r5["installed"]) == 0 and r5["skipped"])

print("\nALL PASS" if allok else "\nSOME FAILED")
