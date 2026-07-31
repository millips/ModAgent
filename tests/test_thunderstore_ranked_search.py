"""Thunderstore natural-language ranking regression tests."""

from modagent.sources import thunderstore


def package(name, description, downloads, owner="Author"):
    return {
        "name": name,
        "full_name": f"{owner}-{name}",
        "owner": owner,
        "package_url": f"https://thunderstore.io/c/repo/p/{owner}/{name}/",
        "total_downloads": downloads,
        "versions": [{
            "version_number": "1.0.0",
            "description": description,
            "downloads": downloads,
            "download_url": "https://example.invalid/package.zip",
            "dependencies": [],
        }],
    }


PACKAGES = [
    package(
        "BetterMap",
        "Displays enemy and teammate positions on the map in real time.",
        876_000,
        "clay",
    ),
    package(
        "Minimap",
        "Adds a customizable minimap and lets spectators see the map.",
        640_000,
        "dig",
    ),
    package(
        "REPO_MiniMap",
        "A real-time mini-map with teammate tracking and zoom controls.",
        12_000,
        "AlbertusJ",
    ),
    package(
        "PlayerHealthBar",
        "Displays player health without changing the map.",
        900_000,
        "Unrelated",
    ),
    package(
        "AllPlayerMapPlayerCount",
        "Automatically applies the Map Player Count upgrade to all players.",
        1_200_000,
        "Unrelated",
    ),
    package(
        "MoreItems",
        "Adds more valuables and loot.",
        2_000_000,
        "Unrelated",
    ),
]


original_packages = thunderstore._packages
thunderstore._packages = lambda community, force_refresh=False: PACKAGES
try:
    results = thunderstore.search("repo", "map player minimap", limit=10)
    names = [item["name"] for item in results]
    assert set(names[:3]) == {"BetterMap", "Minimap", "REPO_MiniMap"}, names
    assert "MoreItems" not in names
    assert names.index("AllPlayerMapPlayerCount") > names.index("BetterMap")
    assert results[0]["search_match"]["coverage"] == 1.0
    assert results[0]["search_match"]["mode"] == "strict"

    chinese = thunderstore.search("repo", "显示队友位置的小地图", limit=10)
    chinese_names = [item["name"] for item in chinese]
    assert set(chinese_names[:3]) == {
        "BetterMap", "Minimap", "REPO_MiniMap"
    }, chinese_names

    compact = thunderstore.search("repo", "minimap", limit=10)
    compact_names = [item["name"] for item in compact]
    assert compact_names[0] == "Minimap", compact_names
    assert {"BetterMap", "REPO_MiniMap"}.issubset(compact_names[:3])

    fallback = thunderstore.search("repo", "map monsters", limit=10)
    assert fallback
    assert fallback[0]["name"] == "BetterMap"
    assert any(
        item["search_match"]["mode"] == "relaxed" for item in fallback
    )

    browse = thunderstore.search("repo", "", limit=2)
    assert [item["name"] for item in browse] == [
        "MoreItems", "AllPlayerMapPlayerCount"
    ]
finally:
    thunderstore._packages = original_packages

print("ALL PASS")
