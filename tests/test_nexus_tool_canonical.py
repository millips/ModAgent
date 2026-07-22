"""Cross-game Nexus tools prefer the maintained canonical entry."""
import json
import types

from modagent import nexus, tools


original_search = nexus.search
original_tool_search = nexus.search_tool_entries

try:
    nexus.search = lambda *args, **kwargs: [{
        "mod_id": 14,
        "name": "Fluffy Mod Manager",
        "author": "FluffyQuack",
        "version": "3.018",
        "updated_time": "2023-09-27T13:10:00Z",
    }]
    nexus.search_tool_entries = lambda *args, **kwargs: [{
        "mod_id": 818,
        "nexus_slug": "site",
        "name": "Fluffy Mod Manager",
        "author": "FluffyQuack",
        "version": "3.079",
        "updated_time": "2026-06-04T23:37:00Z",
        "url": "https://www.nexusmods.com/site/mods/818",
    }]
    cfg = types.SimpleNamespace(
        nexus_api_key="nexus", tavily_api_key="tavily",
        game_slug="streetfighter6", game_id=0,
        game_name="Street Fighter 6", game_root="X:/SF6",
        tier="free", chrome_cdp_port=18888,
    )
    result = json.loads(tools.execute(
        "nexus_search", {"query": "Fluffy Mod Manager"}, cfg
    ))
    entries = result["results"]
    assert entries[0]["mod_id"] == 818
    assert entries[0]["nexus_slug"] == "site"
    assert entries[0]["canonical_candidate"] is True
    old = next(item for item in entries if item["mod_id"] == 14)
    assert old["superseded_by"]["mod_id"] == 818
    assert result["tool_query_global_checked"] is True
finally:
    nexus.search = original_search
    nexus.search_tool_entries = original_tool_search

print("ALL PASS")
