"""Search truthfulness and unknown-game Nexus discovery regression tests."""
import json
import types

from modagent import nexus, tools
from modagent import report_validator as validator
import modagent.sources as sources
from modagent.sources import steam_workshop as workshop
from modagent.sources import thunderstore, gamebanana, github


allok = True


def check(label, condition, detail=""):
    global allok
    print(("PASS " if condition else "FAIL ") + label
          + (f"   {detail}" if detail and not condition else ""))
    allok = allok and bool(condition)


originals = {
    "discover_game": nexus.discover_game,
    "nexus_search": nexus.search,
    "nexus_get_detail": nexus.get_detail,
    "resolve_deps": nexus.resolve_deps,
    "workshop_resolve": workshop.resolve_appid,
    "workshop_search": workshop.search,
    "thunderstore_find": thunderstore.find_community,
    "gamebanana_find": gamebanana.find_game,
    "github_search": github.search,
}

try:
    nexus.discover_game = lambda name, key="": {
        "status": "available",
        "slug": "generic-unknown-game",
        "evidence": "https://www.nexusmods.com/games/generic-unknown-game",
        "reason": "verified",
    }
    workshop.resolve_appid = lambda root: None
    thunderstore.find_community = lambda name: None
    gamebanana.find_game = lambda name: None
    github.search = lambda q, game, limit=5: []
    nexus.search = lambda q, slug, key: []
    nexus.resolve_deps = lambda mid, slug, key: []

    sources._SRC_CACHE.clear()
    found = sources.available_sources(
        "Unknown Game", "", "X:/Games/Unknown", "tvly-key")
    check("A1 unknown game dynamically resolves Nexus",
          found["nexus"] == "generic-unknown-game")
    check("A2 discovery evidence retained",
          found["source_status"]["nexus"]["status"] == "available")

    cfg = types.SimpleNamespace(
        nexus_api_key="nexus-key", tavily_api_key="tvly-key",
        game_slug="", game_id=0, game_name="Unknown Game",
        game_root="X:/Games/Unknown", tier="free", chrome_cdp_port=18888,
    )
    result = json.loads(tools.execute(
        "mod_recommend", {"query": "outfit"}, cfg))
    check("B1 aggregate attempts dynamically discovered Nexus",
          "nexus" in result["sources_attempted"])
    check("B2 empty Nexus is consulted and empty, not unavailable",
          "nexus" in result["sources_consulted"]
          and "nexus" in result["sources_empty"])

    detail_calls = []
    nexus.get_detail = lambda mid, slug, key, cdp_port=18888: (
        detail_calls.append((mid, slug)) or
        {"mod_id": mid, "name": "Verified detail"}
    )
    detail = json.loads(tools.execute(
        "nexus_get_detail", {"mod_id": 2429}, cfg))
    check("B3 detail reuses dynamically discovered Nexus slug",
          detail.get("name") == "Verified detail"
          and detail_calls == [(2429, "generic-unknown-game")])

    persist = [
        {
            "role": "assistant",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "mod_recommend", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": json.dumps(result, ensure_ascii=False),
        },
    ]
    ok_report = validator.validate_search_report(
        "Nexus 本次未搜到匹配服装 Mod；GitHub 本次也未搜到。", persist)
    check("C1 cautious empty-result report allowed", ok_report.ok,
          ok_report.summary())

    false_all = validator.validate_search_report(
        "所有来源都翻了一遍，全网没有服装 Mod。", persist)
    check("C2 all-web absence claim blocked", not false_all.ok)

    false_nexus = validator.validate_search_report(
        "Nexus 没有专区，Steam 创意工坊也确定未收录。", persist)
    check("C3 unsupported platform absence blocked", not false_nexus.ok)

    uncalled = validator.validate_search_report(
        "GameBanana 已搜索，但没有结果。", persist)
    check("C4 unconsulted source claim blocked", not uncalled.ok)

    false_workshop = validator.validate_search_report(
        "Steam 创意工坊专区存在，而且已经开了。", persist)
    check("C5 unverified Workshop availability blocked", not false_workshop.ok)

    fallback = validator.build_search_fallback(persist)
    check("C6 deterministic fallback distinguishes empty and skipped",
          "Nexus：已查询，本次未搜到" in fallback
          and "Steam 创意工坊：本轮未查询" in fallback)
    detail_404 = persist + [
        {"role": "assistant", "tool_calls": [{
            "id": "detail-404", "type": "function",
            "function": {"name": "nexus_get_detail", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "detail-404",
         "content": json.dumps({"error": "HTTP Error 404: Not Found"})},
    ]
    invented_cause = validator.validate_search_report(
        "Nexus API 对成人内容的访问受限，工具侧绕不过去。", detail_404)
    check("C7 a 404 cannot become an adult-content restriction",
          not invented_cause.ok)
finally:
    nexus.discover_game = originals["discover_game"]
    nexus.search = originals["nexus_search"]
    nexus.get_detail = originals["nexus_get_detail"]
    nexus.resolve_deps = originals["resolve_deps"]
    workshop.resolve_appid = originals["workshop_resolve"]
    workshop.search = originals["workshop_search"]
    thunderstore.find_community = originals["thunderstore_find"]
    gamebanana.find_game = originals["gamebanana_find"]
    github.search = originals["github_search"]
    sources._SRC_CACHE.clear()

print("\nALL PASS" if allok else "\nSOME FAILED")
raise SystemExit(0 if allok else 1)
