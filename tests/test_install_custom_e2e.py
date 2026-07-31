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
from modagent import sources, tools

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
preview = json.loads(tools.execute("snapshot_restore", {"snapshot_id": snap_id}, cfg))
rb = json.loads(tools.execute("snapshot_restore", {"snapshot_id": snap_id, "confirmed": True,
                                                     "confirmation_token": preview["confirmation_token"]}, cfg))
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
check("C1 rejects invalid mapping",
      "error" in rc or rc.get("status") == "conflict_blocked")
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

# ── E. 非 Nexus 下载携带稳定来源身份，安装后无需再次搜索对齐 ──
zipE = os.path.join(
    downloader.DOWNLOADS_DIR, "palworld", "ts_Zichen_ModsUp_1.0.5.zip",
)
os.makedirs(os.path.join(G, "BepInEx", "plugins"), exist_ok=True)
source_url = "https://thunderstore.io/c/repo/p/Zichen/ModsUp/"
real_download_from_url = sources.download_from_url
def fake_download_from_url(_url, _slug, progress_callback=None):
    make_zip(zipE, {"ModsUp.dll": "DLL"})
    if progress_callback:
        progress_callback(1)
    return {
        "local_path": zipE,
        "name": "Zichen-ModsUp",
        "source": "thunderstore",
        "version": "1.0.5",
        "dependencies": [],
        "updated_at": "2026-07-01T00:00:00+00:00",
        "detail_verified": True,
        "verification_source": "test_thunderstore_package_api",
        "deprecated": False,
        "staleness": {"stale": False, "age_days": 27},
    }
sources.download_from_url = fake_download_from_url
try:
    downloaded = json.loads(tools.execute(
        "download_from_url", {"url": source_url}, cfg,
    ))
finally:
    sources.download_from_url = real_download_from_url
check("E0 download returns stable source identity",
      downloaded.get("source_key") == "Zichen-ModsUp"
      and downloaded.get("source_url") == source_url,
      f"got {downloaded}")
previewE = json.loads(tools.execute("mod_install_custom", {
    "local_path": downloaded["local_path"],
    "mapping": {"ModsUp.dll": "BepInEx/plugins/ModsUp/ModsUp.dll"},
}, cfg))
check("E0b verified remote package always requires visible preflight",
      previewE.get("status") == "preinstall_confirmation_required"
      and bool(previewE.get("confirmation_token")),
      f"got {previewE}")
rE = json.loads(tools.execute("mod_install_custom", {
    "local_path": downloaded["local_path"],
    "mapping": {"ModsUp.dll": "BepInEx/plugins/ModsUp/ModsUp.dll"},
    "preflight_confirmed": True,
    "preflight_confirmation_token": previewE["confirmation_token"],
}, cfg))
mods_up = next(
    item for item in db.get_installed_mods("palworld")
    if item.name == "ModsUp"
)
binding = db.get_mod_source_binding(mods_up.id, "palworld")
check("E1 downloaded display name/version preserved",
      mods_up.version == "1.0.5", f"mod={mods_up}")
check("E2 Thunderstore source auto-bound",
      binding and binding["source"] == "thunderstore"
      and binding["source_key"] == "Zichen-ModsUp"
      and binding["match_method"] == "download_provenance",
      f"binding={binding}, result={rE}")
check("E3 install result exposes automatic binding",
      rE.get("source_binding", {}).get("source_key") == "Zichen-ModsUp",
      f"got {rE}")
refreshed = tools.refresh_local_inventory(cfg)
binding_after_refresh = db.get_mod_source_binding(mods_up.id, "palworld")
check("E4 offline refresh preserves automatic binding",
      refreshed.get("imported") == 0
      and binding_after_refresh
      and binding_after_refresh["source_key"] == "Zichen-ModsUp",
      f"refresh={refreshed}, binding={binding_after_refresh}")
check("E5 install distinguishes placement from runtime verification",
      rE.get("verification_report", {}).get("dependency_check_complete") is True
      and rE.get("verification_report", {}).get("runtime_effect_verified") is False
      and rE.get("verification_report", {}).get("compatibility_status")
          == "game_build_not_declared",
      f"got {rE}")

# F. An old Thunderstore package must stop before writes and show risk.
zipF = os.path.join(
    downloader.DOWNLOADS_DIR, "palworld",
    "ts_reepchik_BetterItemScanner_1.0.0.zip",
)
make_zip(zipF, {"BetterItemScanner.dll": "DLL"})
downloader.remember_download_provenance(zipF, {
    "source": "thunderstore",
    "game_slug": "palworld",
    "source_key": "reepchik-BetterItemScanner",
    "source_url": "https://thunderstore.io/c/repo/p/reepchik/BetterItemScanner/",
    "name": "reepchik-BetterItemScanner",
    "version": "1.0.0",
    "dependencies": [],
    "updated_at": "2025-03-16T00:00:00+00:00",
    "detail_verified": True,
    "verification_source": "test_thunderstore_package_api",
    "deprecated": False,
    "staleness": {"stale": True, "age_days": 499},
})
better_item_dest = os.path.join(
    G, "BepInEx", "plugins", "BetterItemScanner", "BetterItemScanner.dll",
)
rF = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipF,
    "mapping": {
        "BetterItemScanner.dll":
            "BepInEx/plugins/BetterItemScanner/BetterItemScanner.dll",
    },
}, cfg))
check("F1 stale package requires explicit compatibility confirmation",
      rF.get("status") == "preinstall_confirmation_required"
      and rF.get("requires_confirmation") is True
      and rF.get("compatibility_confirmation_required") is True,
      f"got {rF}")
check("F2 confirmation gate happens before any game write",
      not os.path.exists(better_item_dest), f"got {rF}")
reportF = rF.get("preinstall_report") or {}
check("F3 upstream dependencies and loader are reported separately",
      reportF.get("dependency_check", {}).get("declared_count") == 0
      and reportF.get("dependency_check", {}).get("status")
          == "verified_from_source"
      and reportF.get("runtime_effect_check", {}).get("verified") is False,
      f"got {rF}")
matrixF = {
    "source_detail": reportF.get("source_detail_check", {}),
    "required_dependencies": reportF.get("dependency_check", {}),
    "game_build_compatibility": reportF.get("compatibility_check", {}),
    "runtime_effect": reportF.get("runtime_effect_check", {}),
}
check("F3b four independent verification layers are exposed",
      matrixF.get("source_detail", {}).get("status") == "verified"
      and matrixF.get("required_dependencies", {}).get("declared_count") == 0
      and matrixF.get("game_build_compatibility", {}).get("verified") is False
      and matrixF.get("runtime_effect", {}).get("status") == "not_tested",
      f"got {matrixF}")

rF2 = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipF,
    "mapping": {
        "BetterItemScanner.dll":
            "BepInEx/plugins/BetterItemScanner/BetterItemScanner.dll",
    },
    "preflight_confirmed": True,
    "preflight_confirmation_token": rF["confirmation_token"],
}, cfg))
check("F4 explicit confirmation permits install but not runtime claim",
      rF2.get("installed") == 1
      and os.path.exists(better_item_dest)
      and rF2.get("verification_report", {}).get("runtime_effect_verified")
          is False,
      f"got {rF2}")

# G. A missing declared package dependency must block before writes.
zipG = os.path.join(
    downloader.DOWNLOADS_DIR, "palworld", "ts_Acme_NeedsLibrary_2.0.0.zip",
)
make_zip(zipG, {"NeedsLibrary.dll": "DLL"})
downloader.remember_download_provenance(zipG, {
    "source": "thunderstore",
    "game_slug": "palworld",
    "source_key": "Acme-NeedsLibrary",
    "source_url": "https://thunderstore.io/c/repo/p/Acme/NeedsLibrary/",
    "name": "Acme-NeedsLibrary",
    "version": "2.0.0",
    "dependencies": ["Acme-RequiredLibrary-1.2.0"],
    "updated_at": "2026-07-20T00:00:00+00:00",
    "detail_verified": True,
    "verification_source": "test_thunderstore_package_api",
    "deprecated": False,
    "staleness": {"stale": False, "age_days": 8},
})
missing_dep_dest = os.path.join(
    G, "BepInEx", "plugins", "NeedsLibrary", "NeedsLibrary.dll",
)
rG = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipG,
    "mapping": {
        "NeedsLibrary.dll":
            "BepInEx/plugins/NeedsLibrary/NeedsLibrary.dll",
    },
}, cfg))
check("G1 missing declared dependency blocks installation",
      rG.get("status") == "dependency_blocked"
      and "Acme-RequiredLibrary-1.2.0"
          in (rG.get("missing_dependencies") or []),
      f"got {rG}")
check("G2 missing dependency gate happens before any game write",
      not os.path.exists(missing_dep_dest), f"got {rG}")

# H. Direct installs must expose installed/conflict/dependency checks first.
zipH = os.path.join(
    downloader.DOWNLOADS_DIR, "palworld", "ts_Acme_PreviewOnly_1.0.0.zip",
)
make_zip(zipH, {"PreviewOnly.dll": "DLL"})
provenanceH = {
    "source": "thunderstore",
    "game_slug": "palworld",
    "source_key": "Acme-PreviewOnly",
    "source_url": "https://thunderstore.io/c/repo/p/Acme/PreviewOnly/",
    "name": "Acme-PreviewOnly",
    "version": "1.0.0",
    "dependencies": [],
    "updated_at": "2026-07-20T00:00:00+00:00",
    "detail_verified": True,
    "verification_source": "test_thunderstore_package_api",
    "deprecated": False,
    "staleness": {"stale": False, "age_days": 8},
}
downloader.remember_download_provenance(zipH, provenanceH)
mappingH = {
    "PreviewOnly.dll": "BepInEx/plugins/PreviewOnly/PreviewOnly.dll",
}
previewH = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipH,
    "mapping": mappingH,
    "require_verified_preflight": True,
}, cfg))
check("H1 direct install stops on a full pre-install report",
      previewH.get("status") == "preinstall_confirmation_required"
      and previewH.get("requires_confirmation") is True
      and bool(previewH.get("confirmation_token")),
      f"got {previewH}")
reportH = previewH.get("preinstall_report") or {}
check("H2 installed, conflict and dependency checks are explicit",
      reportH.get("installed_mod_check", {}).get("status") == "not_installed"
      and reportH.get("file_conflict_check", {}).get("status") == "clear"
      and reportH.get("dependency_check", {}).get("status")
          == "verified_from_source",
      f"got {reportH}")
preview_only_dest = os.path.join(
    G, "BepInEx", "plugins", "PreviewOnly", "PreviewOnly.dll",
)
check("H3 preview performs no game write",
      not os.path.exists(preview_only_dest), f"got {previewH}")
installedH = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipH,
    "mapping": mappingH,
    "require_verified_preflight": True,
    "preflight_confirmed": True,
    "preflight_confirmation_token": previewH["confirmation_token"],
}, cfg))
check("H4 one-time user confirmation permits the exact previewed install",
      installedH.get("installed") == 1 and os.path.exists(preview_only_dest),
      f"got {installedH}")

# Recreate the consumed cache archive: exact source identity must now block.
make_zip(zipH, {"PreviewOnly.dll": "DLL"})
downloader.remember_download_provenance(zipH, provenanceH)
duplicateH = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipH,
    "mapping": mappingH,
    "require_verified_preflight": True,
}, cfg))
check("H5 an already-installed source is blocked before overwrite",
      duplicateH.get("status") == "already_installed"
      and duplicateH.get("install_blocked") is True
      and duplicateH.get("preinstall_report", {})
          .get("installed_mod_check", {}).get("status") == "duplicate_found",
      f"got {duplicateH}")

# A different package targeting the same tracked DLL is a hard file conflict.
zipI = os.path.join(
    downloader.DOWNLOADS_DIR, "palworld", "ts_Other_Collision_1.0.0.zip",
)
make_zip(zipI, {"Collision.dll": "OTHER"})
downloader.remember_download_provenance(zipI, {
    **provenanceH,
    "source_key": "Other-Collision",
    "source_url": "https://thunderstore.io/c/repo/p/Other/Collision/",
    "name": "Other-Collision",
})
collisionI = json.loads(tools.execute("mod_install_custom", {
    "local_path": zipI,
    "mapping": {
        "Collision.dll": "BepInEx/plugins/PreviewOnly/PreviewOnly.dll",
    },
    "require_verified_preflight": True,
}, cfg))
check("H6 collision with another installed Mod is blocked before write",
      collisionI.get("status") == "conflict_blocked"
      and collisionI.get("preinstall_report", {})
          .get("file_conflict_check", {}).get("target_conflicts", [])[0]
          .get("kind") == "installed_mod_file"
      and open(preview_only_dest).read() == "DLL",
      f"got {collisionI}")

print("\nALL PASS" if allok else "\nSOME FAILED")
