import os, zipfile, tempfile
from modagent import installer

TMP = tempfile.mkdtemp()

def mkzip(name, files):
    p = os.path.join(TMP, name)
    with zipfile.ZipFile(p, "w") as z:
        for arc, data in files.items():
            z.writestr(arc, data)
    return p

def mkgame():
    g = tempfile.mkdtemp(dir=TMP)
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

# 1. 散 dll -> Mods/ 扁平
g = mkgame()
r = installer.install_mod(mkzip("m1.zip", {"CoolMod.dll": "D", "readme.txt": "r"}), g, "phasmophobia")
allok &= check("1 loose dll -> Mods/ flat", rels(g, r), ["Mods/CoolMod.dll"])
allok &= check("1 readme skipped", r["skipped"], ["readme.txt"])

# 2. 结构化 Mods/ 包 -> 原样合并
g = mkgame()
r = installer.install_mod(mkzip("m2.zip", {"Mods/X.dll": "D", "UserData/X.cfg": "C"}), g, "phasmophobia")
allok &= check("2 structured Mods+UserData merge", rels(g, r), ["Mods/X.dll", "UserData/X.cfg"])

# 3. 嵌套 dll -> 扁平化到 Mods/ 根(MelonLoader 不递归扫)
g = mkgame()
r = installer.install_mod(mkzip("m3.zip", {"bin/Deep.dll": "D"}), g, "phasmophobia")
allok &= check("3 nested dll flattened", rels(g, r), ["Mods/Deep.dll"])

# 4. MelonLoader 自举包(MelonLoader.x64.zip 结构)
g = mkgame()
r = installer.install_mod(mkzip("m4.zip", {
    "MelonLoader/net6/MelonLoader.dll": "M",
    "version.dll": "V", "dobby.dll": "B",
}), g, "phasmophobia")
allok &= check("4 MelonLoader bootstrap merge", rels(g, r),
               ["MelonLoader/net6/MelonLoader.dll", "dobby.dll", "version.dll"])

# 5. 单层壳目录剥壳
g = mkgame()
r = installer.install_mod(mkzip("m5.zip", {"CoolMod-1.2/Mods/Y.dll": "D"}), g, "phasmophobia")
allok &= check("5 wrapper stripped + Mods merge", rels(g, r), ["Mods/Y.dll"])

# 6. 显式 BepInEx 结构包(少数派)
g = mkgame()
r = installer.install_mod(mkzip("m6.zip", {"BepInEx/plugins/Z.dll": "D"}), g, "phasmophobia")
allok &= check("6 explicit BepInEx merge", rels(g, r), ["BepInEx/plugins/Z.dll"])

# 7. UserLibs / Plugins 结构
g = mkgame()
r = installer.install_mod(mkzip("m7.zip", {"UserLibs/dep.dll": "D", "Plugins/P.dll": "P"}), g, "phasmophobia")
allok &= check("7 UserLibs+Plugins merge", rels(g, r), ["Plugins/P.dll", "UserLibs/dep.dll"])

# 8. 纯资源包(无 dll、无已知目录)-> 全部 skipped,不误装
g = mkgame()
r = installer.install_mod(mkzip("m8.zip", {"textures/x.png": "P", "note.md": "n"}), g, "phasmophobia")
allok &= check("8 unmatchable all skipped",
               (rels(g, r), sorted(s.replace("\\", "/") for s in r["skipped"])),
               ([], ["note.md", "textures/x.png"]))

# 9. Mods/ 内嵌套子目录保持(结构化包不扁平)
g = mkgame()
r = installer.install_mod(mkzip("m9.zip", {"Mods/Sub/K.dll": "D"}), g, "phasmophobia")
allok &= check("9 structured Mods keeps nesting", rels(g, r), ["Mods/Sub/K.dll"])

# R1. 回归:剑星散 pak 仍扁平化到 ~mods
g = mkgame(); os.makedirs(os.path.join(g, "SB", "Content", "Paks"))
r = installer.install_mod(mkzip("r1.zip", {"deep/dir/mod_P.pak": "P"}), g, "stellarblade")
allok &= check("R1 stellarblade ~mods flatten intact", rels(g, r),
               ["SB/Content/Paks/~mods/mod_P.pak"])

# R2. 回归:Palworld 散 pak
g = mkgame(); os.makedirs(os.path.join(g, "Pal", "Content", "Paks"))
r = installer.install_mod(mkzip("r2.zip", {"a/b_P.pak": "P"}), g, "palworld")
allok &= check("R2 palworld ~mods flatten intact", rels(g, r),
               ["Pal/Content/Paks/~mods/b_P.pak"])

print("\nALL PASS" if allok else "\nSOME FAILED")
