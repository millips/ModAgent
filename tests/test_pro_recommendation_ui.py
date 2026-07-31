"""Subscription recommendation payloads are stable, bounded and selectable."""
import json

from modagent.recommendation_ui import (
    apply_chinese_descriptions,
    merge_recommendation_resolution,
    normalize_recommendations,
    promote_verified_recommendation,
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
assert framework["installable"] is True
assert framework["resolution_kind"] == "ready"
assert framework["selection_key"] in result["selected_keys"]

workshop_item = next(item for item in result["items"] if item["name"] == "Workshop item")
assert "功能与适配性尚未核验" in workshop_item["content"]
assert workshop_item["has_function_summary"] is False
assert workshop_item["installable"] is False
assert workshop_item["selection_key"] not in result["selected_keys"]
assert workshop_item["resolution_kind"] == "needs_verification"
assert "verify_detail" in workshop_item["resolution_actions"]

no_files = next(item for item in result["items"] if item["name"] == "No files")
assert no_files["installable"] is False
assert no_files["selection_key"] not in result["selected_keys"]
assert no_files["conflict"] == "未提供下载文件"
assert no_files["resolution_kind"] == "manual_download"
assert "manual_import" in no_files["resolution_actions"]

dependency_first = normalize_recommendations({
    "recommendations": [
        {
            "mod_id": 500,
            "name": "Target Outfit",
            "summary": "Adds an outfit",
            "dependencies": ["Dresscode"],
            "_detail_verified": True,
        },
        {
            "mod_id": 501,
            "name": "Dresscode",
            "summary": "Required outfit framework",
            "_detail_verified": True,
        },
    ],
})
assert dependency_first["items"][0]["name"] == "Dresscode"
assert dependency_first["items"][0]["is_prerequisite"] is True
assert dependency_first["items"][0]["required_by"] == ["Target Outfit"]
assert dependency_first["items"][0]["selection_key"] in dependency_first["selected_keys"]
assert dependency_first["dependency_requirements"] == [{
    "name": "Dresscode",
    "required_by": ["Target Outfit"],
    "matched_selection_key": dependency_first["items"][0]["selection_key"],
    "status": "ready",
}]

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
assert evidence_result["items"][0]["installable"] is True
assert evidence_result["items"][0]["resolution_kind"] == "ready"

detail_only = recommendations_from_tool_evidence([
    ("nexus_get_detail", json.dumps({"mod_id": 810, "name": "Physics"})),
])
assert detail_only["items"] == []

loader_blocked = normalize_recommendations({
    "recommendations": [{
        "mod_id": 39,
        "name": "MoneyValueTracker",
        "summary": "Tracks valuables on the map.",
        "dependency_labels": ["RepoLib", "MelonLoader"],
        "required_loader": "MelonLoader",
        "_detail_verified": True,
    }],
}, mod_loader="BepInEx")
blocked_item = loader_blocked["items"][0]
assert blocked_item["installable"] is False
assert blocked_item["resolution_kind"] == "incompatible_loader"
assert blocked_item["required_loader"] == "MelonLoader"
assert blocked_item["active_loader"] == "BepInEx"
assert loader_blocked["selected_keys"] == []

inferred_loader = normalize_recommendations({
    "recommendations": [{
        "mod_id": 17,
        "name": "MorePlayers(BepInEx)",
        "summary": (
            "Changes the maximum player count. Install "
            "YAPYAP_MorePlayers.dll into BepInEx/plugins."
        ),
        "_detail_verified": True,
    }],
}, mod_loader="")
inferred_item = inferred_loader["items"][0]
assert inferred_item["required_loader"] == "BepInEx"
assert inferred_item["dependencies"] == ["BepInEx"]
assert inferred_item["installable"] is False
assert inferred_item["resolution_kind"] == "loader_unverified"
assert inferred_loader["dependency_requirements"][0]["name"] == "BepInEx"
assert inferred_loader["selected_keys"] == []

pending = normalize_recommendations({
    "recommendations": [{
        "mod_id": 233,
        "name": "Admin Menu",
        "summary": "Host administration menu.",
    }],
}, mod_loader="BepInEx")
pending_key = pending["items"][0]["selection_key"]
pending["wanted_keys"] = [pending_key]
promoted = promote_verified_recommendation(
    pending,
    "nexus",
    {
        "mod_id": 233,
        "name": "Admin Menu",
        "summary": "Host administration menu with player controls.",
        "version": "1.1.7",
    },
    mod_loader="BepInEx",
)
assert promoted["items"][0]["detail_verified"] is True
assert promoted["items"][0]["installable"] is True
assert promoted["wanted_keys"] == []
assert promoted["selected_keys"] == [pending_key]
assert promoted["promotion"]["selection_key"] == pending_key

# Resolving one wanted target builds a shared, plan-scoped dependency closure.
# The chosen target and its prerequisite are selected; other candidates that
# need the same planned loader become selectable without being auto-selected.
shared_loader = normalize_recommendations({
    "thunderstore": [
        {
            "name": "Target Alpha",
            "full_name": "Author-TargetAlpha",
            "summary": "Alpha feature.",
            "dependencies": ["BepInEx-BepInExPack-5.4.2305"],
            "required_loader": "BepInEx",
            "url": "https://thunderstore.io/c/test/p/Author/TargetAlpha/",
            "_detail_verified": True,
        },
        {
            "name": "Target Beta",
            "full_name": "Author-TargetBeta",
            "summary": "Beta feature.",
            "dependencies": ["BepInEx-BepInExPack-5.4.2305"],
            "required_loader": "BepInEx",
            "url": "https://thunderstore.io/c/test/p/Author/TargetBeta/",
            "_detail_verified": True,
        },
    ],
}, mod_loader="")
alpha = next(item for item in shared_loader["items"] if item["name"] == "Target Alpha")
beta = next(item for item in shared_loader["items"] if item["name"] == "Target Beta")
assert alpha["installable"] is False
assert beta["installable"] is False
shared_loader["wanted_keys"] = [alpha["selection_key"]]

resolved_loader = normalize_recommendations({
    "thunderstore": [
        {
            "name": "Target Alpha",
            "full_name": "Author-TargetAlpha",
            "summary": "Verified alpha feature.",
            "dependencies": ["BepInEx-BepInExPack-5.4.2305"],
            "required_loader": "BepInEx",
            "url": "https://thunderstore.io/c/test/p/Author/TargetAlpha/",
            "_detail_verified": True,
        },
        {
            "name": "BepInExPack",
            "full_name": "BepInEx-BepInExPack",
            "summary": "BepInEx framework package.",
            "version": "5.4.2305",
            "url": "https://thunderstore.io/c/test/p/BepInEx/BepInExPack/",
            "_detail_verified": True,
        },
    ],
}, mod_loader="")
refreshed = merge_recommendation_resolution(
    shared_loader,
    resolved_loader,
    target_selection_key=alpha["selection_key"],
)
refreshed_alpha = next(
    item for item in refreshed["items"] if item["name"] == "Target Alpha"
)
refreshed_beta = next(
    item for item in refreshed["items"] if item["name"] == "Target Beta"
)
loader_item = next(
    item for item in refreshed["items"] if item["name"] == "BepInExPack"
)
assert refreshed_alpha["installable"] is True
assert refreshed_beta["installable"] is True
assert refreshed_alpha["selection_key"] in refreshed["selected_keys"]
assert refreshed_beta["selection_key"] not in refreshed["selected_keys"]
assert loader_item["selection_key"] in refreshed["selected_keys"]
assert refreshed["wanted_keys"] == []
assert refreshed["resolution_refresh"]["shared_candidates_unlocked"] == 2
assert any(
    requirement["status"] == "planned"
    for requirement in refreshed["dependency_requirements"]
)

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
            "localized_name": "蒂法美人鱼比基尼",
            "content": "替换蒂法服装外观，并提供经过核验的服装细节。",
        },
    ],
})
assert localized["items"][0]["content"].startswith("替换蒂法服装")
assert localized["items"][0]["localized_name"] == "蒂法美人鱼比基尼"
assert localized["items"][0]["name"] == "Tifa Mermaid Bikini"
assert "Verified outfit detail" not in localized["items"][0]["content"]
localized_analysis = recommendation_analysis_text("", localized)
assert "**蒂法美人鱼比基尼 / Tifa Mermaid Bikini**" in localized_analysis
assert all(
    any("\u3400" <= char <= "\u9fff" for char in item["content"])
    for item in localized["items"]
)

# A named installation target must not expand into an open recommendation
# round, and a present BepInEx loader satisfies Thunderstore's package
# coordinate without downloading a second framework copy.
mods_up = recommendations_from_tool_evidence([
    ("nexus_search", json.dumps({
        "results": [
            {
                "mod_id": 900,
                "name": "Unrelated Nexus result",
                "summary": "Not the requested target.",
                "_detail_verified": True,
            },
        ],
    })),
    ("thunderstore_search", json.dumps({
        "results": [
            {
                "name": "ModsUp",
                "full_name": "Zichen-ModsUp",
                "summary": (
                    "REPO游戏交流QQ群: 824639225. "
                    "Runtime compatibility patcher for R.E.P.O."
                ),
                "latest_version": "1.0.5",
                "dependencies": ["BepInEx-BepInExPack-5.4.2100"],
                "url": "https://thunderstore.io/c/repo/p/Zichen/ModsUp/",
                "has_files": True,
                "_detail_verified": True,
            },
            {
                "name": "RepoDarkSoulsPopUpMod",
                "full_name": "MisterBraadorwst-RepoDarkSoulsPopUpMod",
                "summary": "Unrelated search result.",
                "latest_version": "0.2.2",
                "dependencies": ["BepInEx-BepInExPack-5.4.2100"],
                "url": "https://thunderstore.io/c/repo/p/MisterBraadorwst/RepoDarkSoulsPopUpMod/",
                "has_files": True,
                "_detail_verified": True,
            },
        ],
    })),
], mod_loader="BepInEx", target_name="ModsUp", target_version="1.0.5")
assert [item["name"] for item in mods_up["items"]] == ["ModsUp"]
assert mods_up["items"][0]["installable"] is True
assert mods_up["items"][0]["selection_key"] in mods_up["selected_keys"]
assert "824639225" not in mods_up["items"][0]["content"]
assert mods_up["dependency_requirements"] == [{
    "name": "BepInEx-BepInExPack-5.4.2100",
    "required_by": ["ModsUp"],
    "matched_selection_key": "",
    "status": "satisfied_local",
}]

# Dependency aggregation is candidate-scoped and package-version aware.
scoped_dependencies = normalize_recommendations({
    "thunderstore": [
        {
            "name": "Target Alpha",
            "full_name": "Author-TargetAlpha",
            "summary": "Alpha feature.",
            "dependencies": [
                "bbepis-BepInExPack-5.3.1",
                "RiskofThunder-HookGenPatcher-1.2.3",
                "Author-AlphaLibrary-1.0.0",
            ],
            "url": "https://thunderstore.io/c/riskofrain2/p/Author/TargetAlpha/",
            "_detail_verified": True,
        },
        {
            "name": "Target Beta",
            "full_name": "Author-TargetBeta",
            "summary": "Beta feature.",
            "dependencies": [
                "BepInEx-BepInExPack-5.4.2113",
                "RiskofThunder-HookGenPatcher-1.2.9",
                "Author-BetaLibrary-2.0.0",
            ],
            "url": "https://thunderstore.io/c/riskofrain2/p/Author/TargetBeta/",
            "_detail_verified": True,
        },
    ],
}, mod_loader="BepInEx")
assert len(scoped_dependencies["dependency_requirements"]) == 4
bepinex_requirement = next(
    item for item in scoped_dependencies["dependency_requirements"]
    if "BepInExPack" in item["name"]
)
assert bepinex_requirement["status"] == "satisfied_local"
assert bepinex_requirement["version_conflict"] is True
assert bepinex_requirement["requested_versions"] == ["5.4.2113", "5.3.1"]
hook_requirement = next(
    item for item in scoped_dependencies["dependency_requirements"]
    if "HookGenPatcher" in item["name"]
)
assert hook_requirement["name"].endswith("-1.2.9")
assert hook_requirement["version_conflict"] is True

alpha_key = next(
    item["selection_key"] for item in scoped_dependencies["items"]
    if item["name"] == "Target Alpha"
)
scoped_dependencies["selected_keys"] = [alpha_key]
scoped_text = recommendation_analysis_text("", scoped_dependencies)
dependency_summary = scoped_text.split("\n1. ", 1)[0]
assert "AlphaLibrary" in dependency_summary
assert "BetaLibrary" not in dependency_summary

print("ALL PASS")
