"""待修#3:工坊 mod 命名 —— 本地 Info.json 优先于(瞬态不稳的)Steam API,再兜底占位。"""
import os, sys, json, tempfile, types

TMP = tempfile.mkdtemp()
import modagent.scanner as scanner
from modagent.sources import steam_workshop as sw

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: f.write(data)

# 造 Steam 库布局:<lib>/steamapps/common/<game> + <lib>/steamapps/workshop/content/<appid>/<id>/
LIB = os.path.join(TMP, "SteamLibrary")
GAME = os.path.join(LIB, "steamapps", "common", "Palworld")
os.makedirs(GAME, exist_ok=True)
WC = os.path.join(LIB, "steamapps", "workshop", "content", "1623730")

# mod A:有 Info.json(ModName=Pal Analyzer) —— 本地优先应用它
w(os.path.join(WC, "3677771546", "Info.json"),
  json.dumps({"ModName": "Pal Analyzer", "Version": "0.86", "Tags": ["UE4SS", "User Interface"]}))
w(os.path.join(WC, "3677771546", "Paks", "x.pak"), "P")
# mod B:无 Info.json —— 应回退 get_titles,再回退占位
w(os.path.join(WC, "3711425298", "Paks", "y.pak"), "Q")

# 让 resolve_appid 认这个游戏(它按 acf installdir 匹配)
w(os.path.join(LIB, "steamapps", "appmanifest_1623730.acf"),
  '"AppState"\n{\n\t"appid"\t\t"1623730"\n\t"installdir"\t\t"Palworld"\n}')

# 场景1:Steam API 失败(瞬态不稳) → A 靠 Info.json 拿到真名,B 落占位
sw.get_titles = lambda ids: {}
out = {w["id"]: w for w in scanner._scan_steam_workshop(GAME)}
check("A1 local Info.json wins when API fails",
      out.get("ws_3677771546", {}).get("name") == "Pal Analyzer",
      f"got {out.get('ws_3677771546')}")
check("A2 version from Info.json", out.get("ws_3677771546", {}).get("version") == "0.86")
check("A3 no Info.json + API fail → placeholder",
      out.get("ws_3711425298", {}).get("name") == "Workshop 3711425298")

# 场景2:Steam API 可用 → Info.json 仍优先(离线可靠),B 用 API 名
sw.get_titles = lambda ids: {"3677771546": "STEAM-Pal Analyzer", "3711425298": "Humans Reworked"}
out = {w["id"]: w for w in scanner._scan_steam_workshop(GAME)}
check("B1 Info.json still preferred over API", out["ws_3677771546"]["name"] == "Pal Analyzer")
check("B2 API name used when no local", out["ws_3711425298"]["name"] == "Humans Reworked")

# 直接测 helper
n, v = scanner._workshop_local_meta(os.path.join(WC, "3677771546"))
check("C1 helper reads ModName+Version", n == "Pal Analyzer" and v == "0.86")
n, v = scanner._workshop_local_meta(os.path.join(WC, "3711425298"))
check("C2 helper empty when no Info.json", n == "" and v == "")

print("\nALL PASS" if allok else "\nSOME FAILED")
