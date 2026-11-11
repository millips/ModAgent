"""Known failing r4 acceptance check; synthetic data, no model/source calls.

Run: python -m pytest -q evals/r4_negative_evidence_regression.py
This is separate from the previously frozen 108-file regression result.
Do not mark xfail: the failure is an unmet acceptance requirement.
"""
import json

from modagent.recommendation_ui import recommendations_from_tool_evidence


def candidate(summary):
    return recommendations_from_tool_evidence([
        ("nexus_search", json.dumps({
            "query": "training UI",
            "results": [{
                "mod_id": 424242,
                "name": "Training UI",
                "summary": summary,
                "url": "https://www.nexusmods.com/fixturegame/mods/424242",
                "version": "test",
            }],
        })),
    ], game_name="Fixture Game")


def test_relevant_search_evidence_remains_a_candidate():
    # A positive control prevents fixing the negative case by dropping all
    # unverified search results. Unverified is distinct from explicitly false.
    result = candidate("Training assistance and clearer UI for Fixture Game.")
    assert len(result["items"]) == 1
    assert not result["items"][0].get("detail_verified")


def test_explicit_non_mod_evidence_is_not_recommended():
    result = candidate(
        "Training assistance and clearer UI for Fixture Game. "
        "Synthetic evaluation fixture, not a real downloadable Mod."
    )
    assert result["items"] == [], (
        "r4 fallback recommends an explicitly invalid candidate instead of "
        "preserving the negative evidence and returning no valid matches"
    )
