"""Recommendation discovery is enriched before it can enter an install plan."""

from modagent import nexus, tools
from modagent.recommendation_ui import normalize_recommendations


original_search = nexus.search
original_detail = nexus.get_detail


def fake_search(query, slug, api_key, **kwargs):
    return [
        {"mod_id": 10, "name": "Verified", "summary": "Search summary"},
        {"mod_id": 11, "name": "Blocked", "summary": "Search summary"},
        {"mod_id": 0, "name": "Game Nexus - Mods and community"},
    ]


def fake_detail(mod_id, slug, api_key, **kwargs):
    if mod_id == 11:
        raise RuntimeError("Nexus 人机验证")
    return {
        "mod_id": mod_id,
        "name": "Verified",
        "summary": "Authoritative detail",
        "version": "2.0.0",
        "dependencies": [99],
    }


try:
    nexus.search = fake_search
    nexus.get_detail = fake_detail
    result = tools._recommend_nexus("map", "stardewvalley", "", 10)
finally:
    nexus.search = original_search
    nexus.get_detail = original_detail

assert [item["mod_id"] for item in result["recommendations"]] == [10, 11]
verified, blocked = result["recommendations"]
assert verified["_detail_verified"] is True
assert verified["version"] == "2.0.0"
assert blocked["_detail_verified"] is False
assert blocked["verification_status"] == "blocked"
assert "人机验证" in blocked["verification_error"]
assert result["verification"] == {
    "target_ratio": 0.95,
    "attempted": 2,
    "verified": 1,
    "blocked": 1,
    "coverage_ratio": 0.5,
}

ui = normalize_recommendations({
    "recommendations": result["recommendations"],
})
blocked_ui = next(item for item in ui["items"] if item["mod_id"] == 11)
assert blocked_ui["installable"] is False
assert blocked_ui["default_selected"] is False
assert "人机验证" in blocked_ui["conflict"]

print("ALL PASS")
