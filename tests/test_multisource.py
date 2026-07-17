"""#1 收尾:available_sources 识别 + CURRENT STATE 注入 + mod_recommend 多源聚合。
全部 mock 网络依赖,可随时跑;真网行为已人工实测。"""
import os, json, tempfile, types

TMP = tempfile.mkdtemp()
import modagent.db as db
_orig_db_file = db.DB_FILE
db.DB_FILE = os.path.join(TMP, "state.db"); db.init_db()

import modagent.sources as sources
from modagent.sources import thunderstore, gamebanana, steam_workshop as sw, github as gh
from modagent import nexus, tools, prompts
import modagent.config as config

# 本文件按脚本方式执行测试。pytest 收集整个 tests/ 时模块会共享进程，
# 因此必须恢复这些 monkeypatch，避免污染后续搜索与数据库测试。
_originals = {
    "db_get_installed_mods": db.get_installed_mods,
    "thunderstore_find_community": thunderstore.find_community,
    "thunderstore_search": thunderstore.search,
    "gamebanana_find_game": gamebanana.find_game,
    "gamebanana_search": gamebanana.search,
    "workshop_resolve_appid": sw.resolve_appid,
    "workshop_search": sw.search,
    "github_search": gh.search,
    "nexus_search": nexus.search,
    "nexus_resolve_deps": nexus.resolve_deps,
    "config_load_prompt": config.load_prompt,
}

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

# ── A. available_sources:识别与降级 ──
thunderstore.find_community = lambda name: "palworld" if "pal" in (name or "").lower() else None
gamebanana.find_game = lambda name: 19741 if "pal" in (name or "").lower() else None
sw.resolve_appid = lambda root: 1623730 if root else None

sources._SRC_CACHE.clear()
s = sources.available_sources("Palworld", "palworld", "X:/Games/Palworld")
check("A1 all five detected", s["nexus"] and s["workshop"] == 1623730
      and s["thunderstore"] == "palworld" and s["gamebanana"] == 19741 and s["github"] is True)

sources._SRC_CACHE.clear()
s = sources.available_sources("你的老婆", "local_yourwife", "X:/Games/YourWife")
check("A2 local game: nexus off, github on", s["nexus"] is False and s["github"] is True
      and s["thunderstore"] is None and s["gamebanana"] is None)

# 探测炸了 → 降级 None,不抛
def _boom(name): raise OSError("net down")
thunderstore.find_community = _boom
sources._SRC_CACHE.clear()
s = sources.available_sources("Palworld", "palworld", "X:/Games/Palworld")
check("A3 probe failure degrades to None", s["thunderstore"] is None and s["gamebanana"] == 19741)

# 缓存:同游戏第二次不再探测
calls = {"n": 0}
def _counting(name):
    calls["n"] += 1
    return "palworld"
thunderstore.find_community = _counting
sources._SRC_CACHE.clear()
sources.available_sources("Palworld", "palworld", "X:/G")
sources.available_sources("Palworld", "palworld", "X:/G")
check("A4 cached per game", calls["n"] == 1)

# ── B. CURRENT STATE 注入 ──
config.load_prompt = lambda: ""
db.get_installed_mods = lambda slug="": []
sources._SRC_CACHE.clear()
cfg = types.SimpleNamespace(game_root="X:/Games/Palworld", game_slug="palworld", game_name="Palworld")
out = prompts.build_prompt(cfg)
check("B1 sources line injected", "可用 mod 来源" in out and "创意工坊✓(appid 1623730)" in out)
check("B2 forbids searching missing sources", "不要去搜" in out)

# 注入失败不阻塞对话
_orig_avail = sources.available_sources
sources.available_sources = lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
out = prompts.build_prompt(cfg)
check("B3 injection failure degrades silently", "Palworld" in out and "可用 mod 来源" not in out)
sources.available_sources = _orig_avail

# ── C. mod_recommend 多源聚合 ──
nexus.search = lambda q, slug, key: [{"mod_id": 550, "name": "Better Night Light",
                                      "endorsement_count": 99, "updated_time": "2026-06"}]
nexus.resolve_deps = lambda mid, slug, key: []
async def _ws_search(q, appid, port=18888):
    return [{"id": "111", "name": "WS MiniMap", "url": "u"}]
sw.search = _ws_search
thunderstore.find_community = lambda name: None          # 该游戏无 thunderstore
thunderstore.search = lambda c, q, l: []
gamebanana.search = lambda gid, q, l=10: [{"name": "GB Skin", "url": "u", "updated_at": "", "has_files": True}]
gh.search = lambda q, g, limit=5: [{"name": "gh-mod", "full_name": "a/gh-mod", "url": "u",
                                    "summary": "", "stars": 3, "updated_at": "", "archived": False}]
sources._SRC_CACHE.clear()
cfg2 = types.SimpleNamespace(nexus_api_key="k", game_slug="palworld", game_id=0, game_name="Palworld",
                             game_root="X:/Games/Palworld", tier="free", chrome_cdp_port=18888)
r = json.loads(tools.execute("mod_recommend", {"query": "minimap"}, cfg2))
check("C1 nexus compat keys kept", r["recommendations"][0]["mod_id"] == 550 and "install_plan" in r)
check("C2 workshop grouped", r.get("workshop") and r["workshop"][0]["name"] == "WS MiniMap")
check("C3 gamebanana grouped", r.get("gamebanana") and r["gamebanana"][0]["name"] == "GB Skin")
check("C4 github grouped", r.get("github") and r["github"][0]["name"] == "gh-mod")
check("C5 unavailable source not consulted", "thunderstore" not in r["sources_consulted"])
check("C6 consulted lists ok", set(r["sources_consulted"]) == {"nexus", "workshop", "gamebanana", "github"},
      f"got {r['sources_consulted']}")

# 单源失败 → sources_failed,其余不受阻
async def _ws_boom(q, appid, port=18888):
    raise RuntimeError("未找到已登录的 Steam 标签页")
sw.search = _ws_boom
r = json.loads(tools.execute("mod_recommend", {"query": "minimap"}, cfg2))
check("C7 failed source isolated", "workshop" in r["sources_failed"]
      and "Steam" in r["sources_failed"]["workshop"])
check("C8 others unaffected", r["recommendations"] and r.get("github"))

# 空查询早退
r = json.loads(tools.execute("mod_recommend", {"query": ""}, cfg2))
check("C9 empty query early return", r["recommendations"] == [] and "note" in r)

db.DB_FILE = _orig_db_file
db.get_installed_mods = _originals["db_get_installed_mods"]
thunderstore.find_community = _originals["thunderstore_find_community"]
thunderstore.search = _originals["thunderstore_search"]
gamebanana.find_game = _originals["gamebanana_find_game"]
gamebanana.search = _originals["gamebanana_search"]
sw.resolve_appid = _originals["workshop_resolve_appid"]
sw.search = _originals["workshop_search"]
gh.search = _originals["github_search"]
nexus.search = _originals["nexus_search"]
nexus.resolve_deps = _originals["nexus_resolve_deps"]
config.load_prompt = _originals["config_load_prompt"]
sources._SRC_CACHE.clear()

print("\nALL PASS" if allok else "\nSOME FAILED")
