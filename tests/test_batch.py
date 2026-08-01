import os, json, tempfile, types, zipfile

TMP = tempfile.mkdtemp()

import modagent.db as db
db.DB_FILE = os.path.join(TMP, "test_state.db")
db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")
import modagent.downloader as downloader
downloader.DOWNLOADS_DIR = os.path.join(TMP, "downloads")
from modagent import tools

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# 合成恐鬼症(活体)
G = os.path.join(TMP, "Phasmo")
w(os.path.join(G, "Phasmophobia-Win64-Shipping.exe"), "EXE")
os.makedirs(os.path.join(G, "Mods"))

# 两个可装的包 + 一个不存在的 id
dl = os.path.join(downloader.DOWNLOADS_DIR, "phasmophobia")
os.makedirs(dl)
for mid, dll in (("101", "ModA.dll"), ("102", "ModB.dll")):
    with zipfile.ZipFile(os.path.join(dl, f"{mid}_test.zip"), "w") as z:
        z.writestr(dll, "D" * 64)

cfg = types.SimpleNamespace(nexus_api_key="", game_slug="phasmophobia", game_id=3463,
                            game_root=G, tier="free", chrome_cdp_port=18888)

r = json.loads(tools.execute("mod_install_batch", {"mod_ids": ["101", "999", "102"]}, cfg))
check("1 partial download blocks install",
      r.get("status") == "download_incomplete" and r.get("install_blocked") is True)
check("1 missing target identified",
      r.get("total_selected") == 3
      and r.get("ready") == 2
      and any(x.get("mod_id") == "999" for x in r.get("missing", [])))
check("1 no partial files landed",
      not os.path.exists(os.path.join(G, "Mods", "ModA.dll"))
      and not os.path.exists(os.path.join(G, "Mods", "ModB.dll")))
check("1 no snapshot on blocked batch", len(db.list_snapshots("phasmophobia")) == 0)

# 2. 所有选中项都具备下载包后才允许一次性安装
r = json.loads(tools.execute("mod_install_batch", {"mod_ids": ["101", "102"]}, cfg))
check("2 batch ran", r.get("total") == 2)
check("2 all installed", r.get("succeeded") == 2 and r.get("failed") == 0)
check("2 files landed", os.path.exists(os.path.join(G, "Mods", "ModA.dll"))
      and os.path.exists(os.path.join(G, "Mods", "ModB.dll")))

# 3. 整批只有一张快照,且两条 DB 记录共享它
snaps = db.list_snapshots("phasmophobia")
check("3 exactly one snapshot", len(snaps) == 1, f"got {len(snaps)}")
m101, m102 = db.get_mod("101"), db.get_mod("102")
check("3 records share batch snapshot",
      m101 and m102 and m101.snapshot_id == m102.snapshot_id == r["snapshot_id"])

# 4. 空列表/超限防御
e = json.loads(tools.execute("mod_install_batch", {"mod_ids": []}, cfg))
check("4 empty rejected", "error" in e)
e = json.loads(tools.execute("mod_install_batch", {"mod_ids": ["x"] * 31}, cfg))
check("4 >30 rejected", "error" in e and "30" in e["error"])

print("\nALL PASS" if allok else "\nSOME FAILED")
