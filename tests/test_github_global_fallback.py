"""GitHub searches retry globally when a game-scoped tool query is empty."""
from urllib.parse import parse_qs, urlparse

from modagent.sources import github


original_http_json = github._http_json
queries = []


def fake_http_json(url):
    query = parse_qs(urlparse(url).query)["q"][0]
    queries.append(query)
    if "Street Fighter" in query:
        return {"items": []}
    return {"items": [{
        "name": "ModManager",
        "full_name": "fluffy-mods/ModManager",
        "html_url": "https://github.com/fluffy-mods/ModManager",
        "description": "A mod manager",
        "stargazers_count": 100,
        "pushed_at": "2026-07-17T00:00:00Z",
        "archived": False,
    }]}


try:
    github._http_json = fake_http_json
    results = github.search("Fluffy Mod Manager", "Street Fighter 6")
    assert queries == [
        "Fluffy Mod Manager Street Fighter 6",
        "Fluffy Mod Manager",
    ]
    assert results[0]["full_name"] == "fluffy-mods/ModManager"
    assert results[0]["search_scope"] == "global_fallback"
finally:
    github._http_json = original_http_json

print("ALL PASS")
