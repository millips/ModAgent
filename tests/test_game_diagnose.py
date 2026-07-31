"""战役3 块2:game_diagnose —— 框架日志定位 + 错误归因 + 建议。"""
import os, sys, json, tempfile

from modagent import diagnostics as diag
from modagent.db import InstalledMod

TMP = tempfile.mkdtemp()
allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: f.write(data)

def mod(id, name, files):
    return InstalledMod(id=id, name=name, version="1", snapshot_id="",
                        files_installed=json.dumps(files), game_slug="repo")

# ── A. 无日志 → note,不报错 ──
G0 = os.path.join(TMP, "NoLogs"); os.makedirs(G0, exist_ok=True)
r = diag.game_diagnose(G0)
check("A1 no logs → note", r["frameworks"] == [] and "note" in r)

# ── B. BepInEx 日志:error 提及某 mod → 归因 + 建议 ──
G = os.path.join(TMP, "REPO")
w(os.path.join(G, "BepInEx", "LogOutput.log"), "\n".join([
    "[Info   :   BepInEx] Loading [LateJoin 1.2.0]",
    "[Info   :   BepInEx] Loading [MoreHead 1.5.0]",
    "[Error  :   MoreHead] NullReferenceException in MoreHead.Cosmetics.Apply()",
    "[Warning:   BepInEx] LateJoin uses deprecated API",
    "[Info   :   BepInEx] Chainloader startup complete",
]))
mods = [mod("latejoin", "LateJoin", ["/g/BepInEx/plugins/LateJoin/LateJoin.dll"]),
        mod("morehead", "MoreHead", ["/g/BepInEx/plugins/MoreHead/MoreHead.dll"])]
r = diag.game_diagnose(G, "repo", mods)
f = r["findings"][0]
check("B1 BepInEx located", r["frameworks"] == ["BepInEx"] and f["framework"] == "BepInEx")
check("B2 error captured", f["error_count"] >= 1
      and any("NullReference" in e for e in f["recent_errors"]))
check("B3 warning captured", f["warning_count"] >= 1)
attr_names = {a["name"] for a in f["attributed_mods"]}
check("B4 attributed to MoreHead", "MoreHead" in attr_names)
check("B5 suggestion mentions MoreHead", any("MoreHead" in s for s in f["suggestions"]))

# A global exception logger frame identifies who printed an exception, not who
# caused it.  It must not attribute unrelated game/API failures to that Mod.
G_LOGGER = os.path.join(TMP, "GlobalLogger")
w(os.path.join(G_LOGGER, "BepInEx", "LogOutput.log"), "\n".join([
    "[Error  : Unity Log] MissingMethodException: Method not found: void .ValuableObject.Discover(State)",
    "PhysGrabber.DiscoverLogic (UnityEngine.RaycastHit hit)",
    "UnityEngine.DebugLogHandler:LogException(Exception, Object)",
    "MoreHeadBridge.PartShrinkerLogFilter:LogException(Exception, Object)",
    "UnityEngine.Debug:CallOverridenDebugHandler(Exception, Object)",
]))
logger_mods = [
    mod("morehead", "MoreHead", ["/g/BepInEx/plugins/MoreHead/MoreHead.dll"]),
    mod("bridge", "MoreHeadBridge", ["/g/BepInEx/plugins/MoreHeadBridge/MoreHeadBridge.dll"]),
]
logger_result = diag.game_diagnose(G_LOGGER, "repo", logger_mods)["findings"][0]
check("B6 global logger frame is not Mod attribution",
      logger_result["attributed_mods"] == [],
      f"attributed={logger_result['attributed_mods']}")

# ── C. 依赖缺失字样 → dep 建议 ──
G2 = os.path.join(TMP, "DepMiss")
w(os.path.join(G2, "BepInEx", "LogOutput.log"),
  "[Error: BepInEx] Could not find dependency BepInEx.MonoMod for plugin FooMod")
r = diag.game_diagnose(G2, "repo", [])
check("C1 dependency suggestion", any("依赖" in s for s in r["findings"][0]["suggestions"]))

# ── D. UE4SS glob 定位(项目前缀任意)──
G3 = os.path.join(TMP, "StellarBlade")
w(os.path.join(G3, "SB", "Binaries", "Win64", "ue4ss", "UE4SS.log"),
  "[error] Failed to load mod: CNS - version mismatch expected 3.0 got 2.9")
r = diag.game_diagnose(G3, "stellarblade", [])
check("D1 UE4SS located via glob", "UE4SS" in r["frameworks"])
check("D2 version suggestion", any("版本" in s for s in r["findings"][0]["suggestions"]))

# ── E. MelonLoader 定位 ──
G4 = os.path.join(TMP, "Phasmo")
w(os.path.join(G4, "MelonLoader", "Latest.log"), "[15:04:05.123] [Error] some mod crashed")
r = diag.game_diagnose(G4, "phasmophobia", [])
check("E1 MelonLoader located", "MelonLoader" in r["frameworks"])

# ── F. 太短的 mod 名/文件名不参与归因(防误匹配)──
G5 = os.path.join(TMP, "ShortName")
w(os.path.join(G5, "BepInEx", "LogOutput.log"), "[Error] the error mentions abc everywhere")
r = diag.game_diagnose(G5, "repo", [mod("x", "ab", ["/g/x.dll"])])   # name/basename 均 <4 字符
check("F1 short tokens not attributed", r["findings"][0]["attributed_mods"] == [])

# ── G. 纯读取:不改动日志文件 ──
logp = os.path.join(G, "BepInEx", "LogOutput.log")
before = open(logp, encoding="utf-8").read()
diag.game_diagnose(G, "repo", mods)
check("G1 log untouched", open(logp, encoding="utf-8").read() == before)

# ── H. 真实 UE4SS 日志格式(返工靶子):噪音过滤 + ModClass 强信号 + 准确建议 ──
# 防回归:真实 Palworld UE4SS.log 上,通用正则曾漏 "not valid"、误报成员偏移 dump、
# 给"缺依赖"错误建议。这里固化返工后的正确行为。
GH = os.path.join(TMP, "PalReal")
w(os.path.join(GH, "Pal", "Binaries", "Win64", "ue4ss", "UE4SS.log"), "\n".join([
    "[2026] [Info] UE4SS start",
    "[2026] FArchiveState::ArIsError = 0x29",              # 噪音:成员偏移,含 Error 但非错误
    "[2026] UDataTable::bIgnoreMissingFields = 0x80",      # 噪音:含 Missing 但非错误
    "[2026] [Lua] [BPModLoaderMod] Loading mod: DekBasicMinimap_P",
    "[2026] [Lua] [BPModLoaderMod] ModClass for 'DekBasicMinimap_P' is not valid",  # 真错误
    "[2026] [Lua] [BPModLoaderMod] ModClass for 'DekBasicMinimap_P' is not valid",  # 复现
    "[2026] [Lua] [BPModLoaderMod] Actor: ModActor_C ...DekModConfigMenu_P",        # 正常 spawn
]))
mods_h = [mod("bmm", "Basic MiniMap",
              ["/g/Pal/Content/Paks/LogicMods/DekBasicMinimap_P.pak"])]
r = diag.game_diagnose(GH, "palworld", mods_h)
fh = r["findings"][0]
check("H1 noise offset dumps filtered out",
      not any("ArIsError" in e or "bIgnoreMissingFields" in e for e in fh["recent_errors"]),
      f"errors={fh['recent_errors']}")
check("H2 broken_mods catches Basic MiniMap via ModClass signal",
      any(b["mod"] == "Basic MiniMap" for b in fh["broken_mods"]),
      f"broken={fh['broken_mods']}")
check("H3 broken_mods counts both occurrences", fh["broken_mods"][0]["hits"] == 2)
check("H4 suggestion says incompatible, NOT missing-dependency",
      any("不兼容" in s for s in fh["suggestions"])
      and not any("缺前置" in s or "依赖是否装齐" in s for s in fh["suggestions"]),
      f"suggestions={fh['suggestions']}")

print("\nALL PASS" if allok else "\nSOME FAILED")
