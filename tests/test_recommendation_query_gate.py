"""Search sidebars/popularity fallbacks must not enter a focused table."""

import json

from modagent.recommendation_ui import recommendations_from_tool_evidence


payload = recommendations_from_tool_evidence([
    ("gamebanana_search", json.dumps({
        "query": "Raiden Mei",
        "results": [
            {
                "id": "695582",
                "name": "Play as Raiden Mei",
                "summary": "Replace the player model with Raiden Mei.",
                "url": "https://gamebanana.com/mods/695582",
            },
            {
                "id": "111",
                "name": "Play as Sukimi",
                "summary": "A different character replacement.",
                "url": "https://gamebanana.com/mods/111",
            },
            {
                "id": "222",
                "name": "All NSFW T-box mods",
                "summary": "A popular unrelated bundle.",
                "url": "https://gamebanana.com/mods/222",
            },
        ],
    })),
], limit=10)

assert [item["name"] for item in payload["items"]] == ["Play as Raiden Mei"], payload

# Game identity in a title/author is not proof of the requested function.
money_payload = recommendations_from_tool_evidence([(
    "github_search",
    json.dumps({
        "query": "Demonologist money editor",
        "results": [
            {
                "name": "Demonologist-Steam",
                "summary": "Extracted Plugins folder for players who cannot play online.",
                "url": "https://github.com/example/Demonologist-Steam",
            },
            {
                "name": "zanzarah-unbended",
                "summary": "Automatic build script for Zanzarah's Unbended Mod.",
                "author": "Ghost Demonologist",
                "url": "https://github.com/example/zanzarah-unbended",
            },
        ],
    }),
)], game_name="Demonologist", limit=10)
assert money_payload["items"] == [], money_payload
print("RECOMMENDATION QUERY GATE PASSED")
