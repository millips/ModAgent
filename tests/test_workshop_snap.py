import os, json, tempfile, types

TMP = tempfile.mkdtemp()

import modagent.db as db
db.DB_FILE = os.path.join(TMP, "test_state.db")
db.init_db()
import modagent.snapshot as snap
snap.SNAPSHOTS_DIR = os.path.join(TMP, "snapshots")
import modagent.sources.steam_workshop as sw

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

# ── 伪造 Steam 库:acf + 游戏目录 + workshop 内容 ──
LIB = os.path.join(TMP, "SteamLibrary")
G = os.path.join(LIB, "steamapps", "common", "PalTest")
w(os.path.join(G, "Pal", "Binaries", "Win64", "PalTest-Win64-Shipping.exe"), "EXE")
w(os.path.join(LIB, "steamapps", "appmanifest_1623730.acf"),
  '"AppState" { "appid" "1623730" "installdir" "PalTest" "name" "PalTest" }')
WS = os.path.join(LIB, "steamapps", "workshop", "content", "1623730")
w(os.path.join(WS, "111", "mod.pak"), "A")
w(os.path.join(WS, "222", "mod.pak"), "B")

# ── monkeypatch 订阅函数(async,记录调用) ──
calls = {"sub": [], "unsub": []}
async def fake_sub(pid, appid, cdp_port=18888):
    calls["sub"].append(pid); return {"ok": True, "status": 200}
async def fake_unsub(pid, appid, cdp_port=18888):
    calls["unsub"].append(pid); return {"ok": True, "status": 200}
sw.subscribe, sw.unsubscribe = fake_sub, fake_unsub

# 1. create 记录订阅集(基线快照:域空但有工坊订阅)
s0 = snap.snapshot_create(G, "palworld", trigger_mod_name="基线")
m0 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "palworld", s0, "manifest.json"), encoding="utf-8"))
check("1 workshop state recorded", m0.get("workshop") == {"appid": 1623730, "ids": ["111", "222"]})
check("1 still baseline", m0.get("baseline") is True)

# 2. 变更订阅:新订 333,退掉 222 → restore → 差集同步
w(os.path.join(WS, "333", "mod.pak"), "C")
import shutil; shutil.rmtree(os.path.join(WS, "222"))
res = snap.snapshot_restore(s0)
wsr = res["workshop"]
check("2 dict return", isinstance(res, dict) and "files_restored" in res)
check("2 unsubscribed extra", calls["unsub"] == ["333"] and wsr["unsubscribed"] == ["333"])
check("2 resubscribed missing", calls["sub"] == ["222"] and wsr["resubscribed"] == ["222"])

# 3. 已同步状态 → in_sync,不发任何请求
calls["sub"].clear(); calls["unsub"].clear()
shutil.rmtree(os.path.join(WS, "333")); w(os.path.join(WS, "222", "mod.pak"), "B")
res = snap.snapshot_restore(s0)
check("3 in_sync no calls", res["workshop"]["in_sync"] is True and not calls["sub"] and not calls["unsub"])

# 4. CDP 不可用 → manual_*,文件回滚不受阻
async def dead_sub(pid, appid, cdp_port=18888): raise RuntimeError("no chrome")
async def dead_unsub(pid, appid, cdp_port=18888): raise RuntimeError("no chrome")
sw.subscribe, sw.unsubscribe = dead_sub, dead_unsub
w(os.path.join(WS, "444", "mod.pak"), "D")
res = snap.snapshot_restore(s0)
wsr = res["workshop"]
check("4 manual fallback", wsr["manual_unsubscribe"] == ["444"] and "note" in wsr)
check("4 files restore unblocked", "files_restored" in res)

# 5. 非 Steam 布局游戏(resolve 不到 appid)→ workshop=None,一切照旧
G2 = os.path.join(TMP, "Standalone", "Game")
w(os.path.join(G2, "Game-Win64-Shipping.exe"), "EXE")
w(os.path.join(G2, "BepInEx", "plugins", "m.dll"), "M")
s2 = snap.snapshot_create(G2, "some_unknown_game")
m2 = json.load(open(os.path.join(snap.SNAPSHOTS_DIR, "some_unknown_game", s2, "manifest.json"), encoding="utf-8"))
check("5 non-steam game workshop=None", m2.get("workshop") is None)
res = snap.snapshot_restore(s2)
check("5 restore fine without workshop", res["workshop"] is None)

# 6. 工具层:restore 后清理退订 mod 的 DB 记录
sw.subscribe, sw.unsubscribe = fake_sub, fake_unsub
calls["sub"].clear(); calls["unsub"].clear()
shutil.rmtree(os.path.join(WS, "444"))
w(os.path.join(WS, "555", "mod.pak"), "E")
db.add_mod(db.InstalledMod(id="ws_555", name="Workshop 555", version="", snapshot_id="",
                           installed_by="steam_workshop", game_slug="palworld"))
from modagent import tools
cfg = types.SimpleNamespace(nexus_api_key="", game_slug="palworld", game_id=6063,
                            game_root=G, tier="free", chrome_cdp_port=18888)
preview = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s0}, cfg))
r = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s0, "confirmed": True,
                                                    "confirmation_token": preview["confirmation_token"]}, cfg))
check("6 tool returns workshop", r["workshop"]["unsubscribed"] == ["555"])
check("6 db row cleaned", db.get_mod("ws_555") is None)

print("\nALL PASS" if allok else "\nSOME FAILED")
