import os, zipfile, tempfile, shutil
from modagent import installer

TMP = tempfile.mkdtemp()

def mkzip(name, files):
    p = os.path.join(TMP, name)
    with zipfile.ZipFile(p, "w") as z:
        for arc, data in files.items():
            z.writestr(arc, data)
    return p

def mkgame(with_bep=False):
    g = tempfile.mkdtemp(dir=TMP)
    if with_bep:
        os.makedirs(os.path.join(g, "BepInEx", "core"))
        open(os.path.join(g, "winhttp.dll"), "w").close()
    return g

def rels(game, r):
    return sorted(os.path.relpath(x["dest"], game).replace("\\", "/") for x in r["installed"])

def check(label, got, expect):
    ok = got == expect
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        print("   got   :", got)
        print("   expect:", expect)
    return ok

allok = True

# 1. plugins/ 布局标准 mod(她 R.E.P.O. 已装 BepInEx)
g = mkgame(with_bep=True)
z = mkzip("ts_nickklmao_MoreHead_1.2.3.zip", {
    "manifest.json": "{}", "icon.png": "x", "README.md": "hi",
    "plugins/MoreHead.dll": "DLL",
})
r = installer.install_mod(z, g, "repo")
allok &= check("1 plugins/ -> BepInEx/plugins/<pkg>/", rels(g, r),
               ["BepInEx/plugins/nickklmao_MoreHead/MoreHead.dll"])
allok &= check("1 metadata skipped", sorted(r["skipped"]),
               ["README.md", "icon.png", "manifest.json"])

# 2. 包自带 BepInEx/ 前缀
g = mkgame(with_bep=True)
z = mkzip("ts_a_b_1.0.zip", {"manifest.json": "{}", "BepInEx/plugins/Mod.dll": "D"})
r = installer.install_mod(z, g, "repo")
allok &= check("2 BepInEx/ prefix -> merge", rels(g, r), ["BepInEx/plugins/Mod.dll"])

# 3. 散 dll
g = mkgame(with_bep=True)
z = mkzip("ts_a_LooseMod_1.0.zip", {"manifest.json": "{}", "LooseMod.dll": "D"})
r = installer.install_mod(z, g, "repo")
allok &= check("3 loose dll -> plugins/<pkg>/", rels(g, r),
               ["BepInEx/plugins/a_LooseMod/LooseMod.dll"])

# 4. patchers + config
g = mkgame(with_bep=True)
z = mkzip("ts_a_Patch_1.0.zip", {
    "manifest.json": "{}", "patchers/Pre.dll": "D", "config/my.cfg": "C",
})
r = installer.install_mod(z, g, "repo")
allok &= check("4 patchers/config routing", rels(g, r),
               ["BepInEx/config/my.cfg", "BepInEx/patchers/a_Patch/Pre.dll"])

# 5. BepInExPack 自举(裸游戏,壳目录 BepInExPack/ 里藏 BepInEx/)
g = mkgame(with_bep=False)
z = mkzip("ts_BepInEx_BepInExPack_5.4.zip", {
    "manifest.json": "{}", "icon.png": "x", "README.md": "hi",
    "BepInExPack/winhttp.dll": "W",
    "BepInExPack/doorstop_config.ini": "I",
    "BepInExPack/BepInEx/core/BepInEx.Core.dll": "C",
})
r = installer.install_mod(z, g, "repo")
allok &= check("5 BepInExPack bootstrap -> merge to root", rels(g, r),
               ["BepInEx/core/BepInEx.Core.dll", "doorstop_config.ini", "winhttp.dll"])

# 6. 不可识别包(无 dll、无已知目录)-> 必须报错
g = mkgame(with_bep=True)
z = mkzip("ts_a_Textures_1.0.zip", {"manifest.json": "{}", "data/tex.png": "P"})
try:
    installer.install_mod(z, g, "repo")
    allok &= check("6 unrecognizable raises", "no-raise", "RuntimeError")
except RuntimeError:
    allok &= check("6 unrecognizable raises", "raised", "raised")

# 7. GitHub 式单层壳目录
g = mkgame(with_bep=True)
z = mkzip("ts_a_Wrapped_1.0.zip", {"Wrapped-1.0/plugins/X.dll": "D"})
r = installer.install_mod(z, g, "repo")
allok &= check("7 single wrapper dir stripped", rels(g, r),
               ["BepInEx/plugins/a_Wrapped/X.dll"])

# 8. 裸游戏装普通 mod -> 有 note 提示缺加载器
g = mkgame(with_bep=False)
z = mkzip("ts_a_Mod_1.0.zip", {"plugins/M.dll": "D"})
r = installer.install_mod(z, g, "repo")
note_ok = any("BepInExPack" in n for n in r.get("notes", []))
allok &= check("8 bare game -> loader-missing note", note_ok, True)

print("\nALL PASS" if allok else "\nSOME FAILED")
