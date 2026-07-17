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
check("1 batch ran", r.get("total") == 3)
check("1 2 ok 1 fail", r.get("succeeded") == 2 and r.get("failed") == 1)
check("1 failure identified", any(x["mod_id"] == "999" and not x["ok"] for x in r["results"]))

# 2. 文件真实落位
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
