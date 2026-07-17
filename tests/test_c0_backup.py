import os, zipfile, tempfile
from modagent import installer

TMP = tempfile.mkdtemp()
installer.BACKUPS_DIR = os.path.join(TMP, "central_backups")   # 隔离集中区

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(data)

def mkzip(name, files):
    p = os.path.join(TMP, name)
    with zipfile.ZipFile(p, "w") as z:
        for arc, data in files.items(): z.writestr(arc, data)
    return p

def find_baks(root):
    return [os.path.join(r, f) for r, _, fs in os.walk(root) for f in fs if f.endswith(".modagent_bak")]

# ── 场景:恐鬼症,已有同名 dll,覆盖安装 ──
G = os.path.join(TMP, "Phasmo")
DEST = os.path.join(G, "Mods", "CoolMod.dll")
w(DEST, "ORIGINAL")
os.makedirs(os.path.join(G, "Mods"), exist_ok=True)

r = installer.install_mod(mkzip("m1.zip", {"CoolMod.dll": "NEW_V1"}), G, "phasmophobia")
check("1 installed new content", open(DEST).read() == "NEW_V1")
check("1 NO in-place bak in game dir", find_baks(G) == [])
central = os.path.join(installer.BACKUPS_DIR, "phasmophobia", "Mods", "CoolMod.dll")
check("1 central backup holds original", os.path.exists(central) and open(central).read() == "ORIGINAL")

# 2. 再次覆盖安装 → keep-first(备份仍是最初版本)
r = installer.install_mod(mkzip("m2.zip", {"CoolMod.dll": "NEW_V2"}), G, "phasmophobia")
check("2 keep-first backup", open(central).read() == "ORIGINAL")
check("2 still no in-place bak", find_baks(G) == [])

# 3. 卸载 → mod 文件移除,原文件从集中区还原(shutil.move,跨目录安全)
r = installer.uninstall_mod("m1", G, [DEST], game_slug="phasmophobia")
check("3 original restored", open(DEST).read() == "ORIGINAL")
check("3 central backup consumed", not os.path.exists(central))
check("3 result records restore", DEST in r.get("restored_original", []))

# 4. 旧版原地 bak 兼容:手工植入 sibling bak → 卸载仍能还原
DEST2 = os.path.join(G, "Mods", "OldStyle.dll")
w(DEST2, "MODDED"); w(DEST2 + ".modagent_bak", "LEGACY_ORIG")
r = installer.uninstall_mod("m2", G, [DEST2], game_slug="phasmophobia")
check("4 legacy sibling bak restored", open(DEST2).read() == "LEGACY_ORIG")
check("4 legacy bak gone", not os.path.exists(DEST2 + ".modagent_bak"))

# 5. 文件已丢但备份在 → 清孤儿账,不复活文件
DEST3 = os.path.join(G, "Mods", "Ghost.dll")
w(DEST3 + ".modagent_bak", "GHOST")
r = installer.uninstall_mod("m3", G, [DEST3], game_slug="phasmophobia")
check("5 orphan bak cleaned, file not resurrected",
      not os.path.exists(DEST3) and not os.path.exists(DEST3 + ".modagent_bak"))

# 6. BepInEx 路径同样走集中区
G2 = os.path.join(TMP, "Repo")
os.makedirs(os.path.join(G2, "BepInEx", "plugins"), exist_ok=True)
PRE = os.path.join(G2, "BepInEx", "plugins", "bepmod", "P.dll")
w(PRE, "BEP_ORIG")
r = installer.install_mod(mkzip("bepmod.zip", {"plugins/P.dll": "BEP_NEW"}), G2, "repo")
check("6 bepinex overwrote", open(PRE).read() == "BEP_NEW")
check("6 bepinex path no in-place bak", find_baks(G2) == [])
c2 = os.path.join(installer.BACKUPS_DIR, "repo", "BepInEx", "plugins", "bepmod", "P.dll")
check("6 bepinex central backup", os.path.exists(c2) and open(c2).read() == "BEP_ORIG")

print("\nALL PASS" if allok else "\nSOME FAILED")
