"""Subscription recommendation payloads are stable, bounded and selectable."""
import json

from modagent.recommendation_ui import (
    apply_chinese_descriptions,
    normalize_recommendations,
    recommendation_analysis_text,
    recommendations_from_tool_evidence,
)


payload = {
    "recommendations": [
        {
            "mod_id": 101,
            "name": "Framework",
            "summary": "Loads costume mods",
            "version": "1.2.0",
            "updated_at": "2026-07-01",
            "dependencies": [9],
            "_detail_verified": True,
        },
        {"mod_id": 102, "name": "Nexus second"},
    ],
    "workshop": [{"id": "202", "name": "Workshop item"}],
    "thunderstore": [
        {
            "full_name": "Owner-Package",
            "name": "Package",
            "summary": "Adds a feature",
            "url": "https://thunderstore.io/package/Owner/Package/",
            "_detail_verified": True,
        }
    ],
    "gamebanana": [
        {
            "name": "No files",
            "url": "https://gamebanana.com/mods/303",
            "has_files": False,
        }
    ],
    "github": [
        {
            "full_name": "owner/repo",
            "name": "Repo",
            "summary": "Tooling",
            "url": "https://github.com/owner/repo",
            "updated_at": "2026-06-01",
            "_detail_verified": True,
        },
        {
            "full_name": "owner/archived",
            "name": "Archived",
            "url": "https://github.com/owner/archived",
            "archived": True,
        },
    ],
}

result = normalize_recommendations(json.dumps(payload), limit=6)
assert result["kind"] == "recommendation_set"
assert len(result["items"]) == 6
assert [item["source"] for item in result["items"][:5]] == [
    "nexus", "workshop", "thunderstore", "gamebanana", "github",
]
assert len(result["selected_keys"]) == 3
assert result["verification"]["verified"] == 3
assert result["verification"]["coverage_ratio"] == 0.5
assert len(set(item["selection_key"] for item in result["items"])) == 6

many = normalize_recommendations({
    "recommendations": [
        {"mod_id": index, "name": f"Candidate {index}", "summary": "Feature"}
        for index in range(1, 16)
    ],
})
assert len(many["items"]) == 10
assert len(normalize_recommendations({
    "recommendations": [
        {"mod_id": index, "name": f"Candidate {index}", "summary": "Feature"}
        for index in range(1, 25)
    ],
}, limit=20)["items"]) == 20
assert len(normalize_recommendations({
    "recommendations": [
        {"mod_id": index, "name": f"Candidate {index}", "summary": "Feature"}
        for index in range(1, 8)
    ],
}, limit=1)["items"]) == 2

framework = result["items"][0]
assert framework["version"] == "1.2.0"
assert framework["dependencies"] == ["9"]
assert framework["content"] == "Loads costume mods"

workshop_item = next(item for item in result["items"] if item["name"] == "Workshop item")
assert "功能与适配性尚未核验" in workshop_item["content"]
assert workshop_item["has_function_summary"] is False
assert workshop_item["installable"] is False
assert workshop_item["selection_key"] not in result["selected_keys"]

no_files = next(item for item in result["items"] if item["name"] == "No files")
assert no_files["installable"] is False
assert no_files["selection_key"] not in result["selected_keys"]
assert no_files["conflict"] == "未提供下载文件"

rich = normalize_recommendations({
    "recommendations": [{
        "mod_id": 5245,
        "name": "Become Adam Smasher - Male V",
        "summary": "Turns Male V into Adam Smasher.",
        "description": (
            "Works in first and third person. Gorilla Arms must be equipped "
            "for Adam Smasher's arms to appear."
        ),
        "_detail_verified": True,
    }],
})
assert "first and third person" in rich["items"][0]["content"]
assert "Gorilla Arms" in rich["items"][0]["content"]

evidence_result = recommendations_from_tool_evidence([
    ("mod_recommend", json.dumps({
        "recommendations": [
            {"mod_id": 4, "name": "Irrelevant framework"},
        ],
    })),
    ("nexus_search", json.dumps({
        "results": [
            {"mod_id": 816, "name": "Tifa Mermaid Bikini", "version": "1.1"},
            {"mod_id": 747, "name": "Aerith Sexy Dress"},
        ],
    })),
    ("nexus_get_detail", json.dumps({
        "mod_id": 816,
        "name": "Tifa Mermaid Bikini",
        "summary": "Verified outfit detail",
        "version": "1.2",
        "requirements": [{"name": "Dresscode"}],
    })),
    ("nexus_get_detail", json.dumps({
        "mod_id": 1791,
        "name": "Aerith Sexy Red Dress",
        "summary": "19 colors",
    })),
])
assert [item["mod_id"] for item in evidence_result["items"][:2]] == [816, 1791]
assert evidence_result["items"][0]["version"] == "1.2"
assert evidence_result["items"][0]["dependencies"] == ["Dresscode"]
assert evidence_result["items"][0]["detail_verified"] is True
assert evidence_result["items"][0]["dependency_status"] == "known"
assert evidence_result["items"][0]["conflict_status"] == "clear"
assert "详情已核验" in evidence_result["items"][0]["recommendation_reason"]
assert evidence_result["items"][1]["version"] == "待详情核验"
assert len(evidence_result["selected_keys"]) == 2

detail_only = recommendations_from_tool_evidence([
    ("nexus_get_detail", json.dumps({"mod_id": 810, "name": "Physics"})),
])
assert detail_only["items"] == []

analysis = recommendation_analysis_text("""
## 推荐与分析
| # | Mod | 版本 |
|---|---|---|
| 1 | Bikini | 1.1 |

- **Bikini**：更新时间较新，适合作为优先候选。
- 风险：安装前仍需核对 Dresscode 依赖。
""")
assert "推荐与分析" in analysis
assert "更新时间较新" in analysis
assert "Dresscode 依赖" in analysis
assert "| # |" not in analysis
assert "| 1 |" not in analysis
assert "下方清单" in analysis

complete_analysis = recommendation_analysis_text("", evidence_result)
assert "1. **Tifa Mermaid Bikini** (Nexus #816)" in complete_analysis
assert "2. **Aerith Sexy Red Dress** (Nexus #1791)" in complete_analysis

localized = apply_chinese_descriptions(evidence_result, {
    "items": [
        {
            "selection_key": evidence_result["items"][0]["selection_key"],
            "content": "替换蒂法服装外观，并提供经过核验的服装细节。",
        },
    ],
})
assert localized["items"][0]["content"].startswith("替换蒂法服装")
assert "Verified outfit detail" not in localized["items"][0]["content"]
assert all(
    any("\u3400" <= char <= "\u9fff" for char in item["content"])
    for item in localized["items"]
)

print("ALL PASS")
