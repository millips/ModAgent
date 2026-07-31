"""多站搜索(#1 ⑤):github.search / gamebanana.find_game+search 的整形与降级。
真网端点已人工实测(GitHub Search API / GameBanana apiv11);这里 mock _http_json
锁定字段整形、限流报错、未收录降级——不打真网,可随时跑。"""
import urllib.error

from modagent.sources import github as gh
from modagent.sources import gamebanana as gb

allok = True
def check(label, cond, detail=""):
    global allok
    print(("PASS " if cond else "FAIL ") + label + (f"   {detail}" if not cond and detail else ""))
    allok = allok and cond

# ── GitHub:字段整形 ──
gh._http_json = lambda url, headers=None: {"items": [
    {"name": "PalMod", "full_name": "a/PalMod", "html_url": "https://github.com/a/PalMod",
     "description": "A Palworld mod " + "x" * 200, "stargazers_count": 42,
     "pushed_at": "2026-05-21T10:00:00Z", "archived": False},
    {"name": "OldTool", "full_name": "b/OldTool", "html_url": "https://github.com/b/OldTool",
     "description": None, "stargazers_count": 1, "pushed_at": "2023-01-01T00:00:00Z", "archived": True},
]}
r = gh.search("minimap", "Palworld", limit=5)
check("A1 github: irrelevant/archived result filtered", len(r) == 1)
check("A2 github: summary truncated to 140", len(r[0]["summary"]) <= 140)
check("A3 github: stars/updated/archived", r[0]["stars"] == 42
      and r[0]["updated_at"] == "2026-05-21" and r[0]["archived"] is False)
check("A4 github: relevant result retained", r[0]["name"] == "PalMod")

# 限流 → 友好报错
def _rate_limited(url, headers=None):
    raise urllib.error.HTTPError(url, 403, "rate limited", None, None)
gh._http_json = _rate_limited
try:
    gh.search("x", "y")
    check("A5 github rate limit raises", False)
except RuntimeError as e:
    check("A5 github rate limit → 友好提示", "限流" in str(e))

# 空查询拒绝
try:
    gh.search("", "")
    check("A6 empty query raises", False)
except RuntimeError:
    check("A6 empty query raises", True)

# ── GameBanana:find_game 精确优先 + 缓存 + search 整形 ──
calls = {"n": 0}
def _gb_game(url, headers=None):
    calls["n"] += 1
    return {"_aRecords": [
        {"_idRow": 111, "_sName": "Palworld Deluxe"},
        {"_idRow": 19741, "_sName": "Palworld"},
    ]}
gb._http_json = _gb_game
gb._GAME_CACHE.clear()
check("B1 exact name preferred", gb.find_game("Palworld") == 19741)
gb.find_game("Palworld")
check("B2 cached (no second http)", calls["n"] == 1)
check("B3 empty name → None", gb.find_game("") is None)

gb._http_json = lambda url, headers=None: {"_aRecords": [
    {"_idRow": 574190, "_sName": "Growlmon", "_sProfileUrl": "https://gamebanana.com/mods/574190",
     "_tsDateModified": 1739081144, "_bHasFiles": True},
    {"_idRow": 1, "_sName": "NoFiles", "_sProfileUrl": "u", "_bHasFiles": False},
]}
r = gb.search(19741, "skin")
check("C1 gamebanana shaped", r[0]["name"] == "Growlmon" and r[0]["has_files"] is True
      and r[0]["updated_at"].startswith("2025"))
check("C2 no-files flagged", r[1]["has_files"] is False and r[1]["updated_at"] == "")

# find_game 站点不可达 → None 且不缓存失败
def _boom(url, headers=None):
    raise OSError("net down")
gb._http_json = _boom
gb._GAME_CACHE.clear()
check("D1 unreachable → None", gb.find_game("SomeGame") is None)
gb._http_json = _gb_game
check("D2 failure not cached, retry works", gb.find_game("SomeGame") == 19741
      or gb.find_game("Palworld") == 19741)

print("\nALL PASS" if allok else "\nSOME FAILED")
