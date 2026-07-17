"""T2 第3块:mod_install_custom 工具编排端到端(过 tools.execute)。

覆盖:
  A. 编排顺序 + 铁律6 端到端:覆盖游戏原文件 → 安装前快照含原文件 → 回滚还原原文件
     (证明"先登记域→建快照→落位"顺序在真实工具路径上成立)
  B. DB 记账:custom mod 写入 installed_mods,custom_domain 登记
  C. 全非法 mapping → 返回 error,不写 DB 空账
  D. mod_install 开放模式失败 → 返回 hint 引导走 mod_install_custom
"""
import os, sys, json, tempfile, types, zipfile

TMP = tempfile.mkdtemp()

import modagent.config as config
config.CONFIG_DIR = os.path.join(TMP, "cfgdir")
os.makedirs(config.CONFIG_DIR, exist_ok=True)
import importlib
import modagent.db as db
db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")
import modagent.installer as installer
importlib.reload(installer)
import modagent.downloader as downloader
from modagent import tools

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def make_zip(path, files: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# palworld(硬编码域):Shipping exe 过活体;落点选在 Pal/Content/Localization(不在 pak 快照域内)
G = os.path.join(TMP, "Palworld")
w(os.path.join(G, "Pal", "Binaries", "Win64", "Palworld-Win64-Shipping.exe"), "EXE")
LOC_REL = "Pal/Content/Localization/Game/zh-Hans/Game.locres"
LOC = os.path.join(G, LOC_REL.replace("/", os.sep))
w(LOC, "ORIGINAL")   # 游戏原版自带的本地化文件(非常规落点,自动规则不管)

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="palworld", game_id=6063,
                            game_root=G, tier="free", chrome_cdp_port=18888)

# ── A/B. 覆盖游戏原文件的通用安装,端到端 ──
zipA = os.path.join(TMP, "loc_mod.zip")
make_zip(zipA, {"Game.locres": "MODDED-ZH"})
r = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipA,
    "mapping": {"Game.locres": LOC_REL},
}, cfg))
check("A1 installed 1 file", r.get("installed") == 1, f"got {r}")
check("A2 custom domain registered", LOC_REL in (r.get("custom_domain_registered") or []))
check("A3 overwrite applied on disk", open(LOC).read() == "MODDED-ZH")
snap_id = r["snapshot_id"]
# 安装前快照必须含该原文件(先登记域才做到 → 原文件受保护)
m = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "palworld", snap_id, "manifest.json"), encoding="utf-8"))
check("A4 pre-install snapshot protected original", LOC_REL in m["files"])
# DB 记账
custom_mods = [x for x in db.get_installed_mods("palworld") if x.installed_by == "custom"]
check("B1 custom mod recorded in DB", len(custom_mods) == 1
      and LOC in json.loads(custom_mods[0].files_installed))
check("B2 domain persisted", LOC_REL in db.get_custom_domain_files("palworld"))

# 端到端回滚:回到安装前 → 游戏原文件还原成 ORIGINAL(铁律6 在真实工具路径成立)
rb = json.loads(tools.execute("snapshot_restore", {"snapshot_id": snap_id}, cfg))
check("A5 rollback restored ORIGINAL game file", open(LOC).read() == "ORIGINAL",
      f"content={open(LOC).read()!r}, rb={rb}")

# ── C. 全非法 mapping → error,不写空账 ──
before = len(db.get_installed_mods("palworld"))
zipC = os.path.join(TMP, "bad.zip")
make_zip(zipC, {"x.txt": "X"})
rc = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipC,
    "mapping": {"x.txt": "../../evil.txt"},   # 越界逃逸
}, cfg))
check("C1 returns error", "error" in rc)
check("C2 no DB row written", len(db.get_installed_mods("palworld")) == before)
check("C3 nothing escaped", not os.path.exists(os.path.join(os.path.dirname(TMP), "evil.txt")))

# ── D. mod_install 开放模式失败 → hint 引导 custom ──
# palworld 有 pak 落位规则,但包里只有无关 .txt → 全 skip → files_installed 空 → hint
downloader.DOWNLOADS_DIR = os.path.join(TMP, "downloads")
zipD = os.path.join(TMP, "downloads", "palworld", "9999_nothing.zip")
make_zip(zipD, {"random.txt": "nope", "notes.md": "hi"})
rd = json.loads(tools.execute("mod_install", {"mod_id": 9999, "local_path": zipD}, cfg))
check("D1 install returns hint to custom", rd.get("installed") == 0
      and "mod_install_custom" in rd.get("hint", ""), f"got {rd}")
check("D2 no ghost mod row for failed install", db.get_mod("9999") is None)

print("\nALL PASS" if allok else "\nSOME FAILED")
