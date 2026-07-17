"""靶向文件夹(#1 多源第一块):list_local_mods 列出投放文件夹 + 下载缓存的本地 mod。"""
import os, json, tempfile, types

TMP = tempfile.mkdtemp()
import modagent.config as config
config.CONFIG_DIR = os.path.join(TMP, "cfg"); os.makedirs(config.CONFIG_DIR, exist_ok=True)
import importlib
import modagent.downloader as downloader
importlib.reload(downloader)   # 让 DROPBOX_DIR 吃到隔离后的 CONFIG_DIR
downloader.DOWNLOADS_DIR = os.path.join(TMP, "downloads")
import modagent.db as db
db.DB_FILE = os.path.join(TMP, "state.db"); db.init_db()
from modagent import tools

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="repo", game_id=0,
                            game_root=TMP, tier="free", chrome_cdp_port=18888)

# ── 空投放文件夹 → note 指路 ──
r = json.loads(tools.execute("list_local_mods", {}, cfg))
check("A1 empty → note with path", r["local_mods"] == [] and "dropbox_path" in r and "note" in r)
check("A2 dropbox path under CONFIG_DIR/dropbox/slug",
      r["dropbox_path"].replace("\\", "/").endswith("dropbox/repo"))

# ── 投放文件夹放两个包 + 一个非压缩包(应忽略)──
drop = downloader.ensure_dropbox_dir("repo")
w(os.path.join(drop, "SglynpMod_v2.zip"), "Z" * 1000)     # 三宫六院手动下载的
w(os.path.join(drop, "networkdisk_mod.rar"), "R" * 2000)  # 网盘下载的 rar
w(os.path.join(drop, "readme.txt"), "not a mod")          # 非压缩包,忽略
# 下载缓存放一个
w(os.path.join(downloader.DOWNLOADS_DIR, "repo", "123_auto.zip"), "A" * 500)

r = json.loads(tools.execute("list_local_mods", {}, cfg))
names = {m["name"]: m for m in r["local_mods"]}
check("B1 lists zip+rar from dropbox", "SglynpMod_v2.zip" in names and "networkdisk_mod.rar" in names)
check("B2 ignores non-archive", "readme.txt" not in names)
check("B3 includes download cache", "123_auto.zip" in names)
check("B4 source labeled",
      names["SglynpMod_v2.zip"]["source"] == "投放文件夹"
      and names["123_auto.zip"]["source"] == "下载缓存")
check("B5 path is absolute + exists", all(os.path.isfile(m["path"]) for m in r["local_mods"]))
check("B6 size reported", names["networkdisk_mod.rar"]["size_mb"] >= 0)

# ── 去重:同名文件在两个目录只列一次(投放优先)──
w(os.path.join(downloader.DOWNLOADS_DIR, "repo", "SglynpMod_v2.zip"), "dup")
r = json.loads(tools.execute("list_local_mods", {}, cfg))
dups = [m for m in r["local_mods"] if m["name"] == "SglynpMod_v2.zip"]
check("C1 dedup same name across dirs", len(dups) == 1 and dups[0]["source"] == "投放文件夹")

print("\nALL PASS" if allok else "\nSOME FAILED")
