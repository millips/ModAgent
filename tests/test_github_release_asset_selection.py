"""GitHub releases must select the runnable Windows archive."""

import json
from unittest.mock import patch

from modagent.tools import _resolve_github_release_url
from modagent.sources.github import pick_release_asset


def asset(name: str, size: int = 1) -> dict:
    return {
        "name": name,
        "size": size,
        "browser_download_url": f"https://example.invalid/{name}",
    }


bepinex_assets = [
    asset("BepInEx_linux_x64_5.4.23.5.zip", 643325),
    asset("BepInEx_linux_x86_5.4.23.5.zip", 643312),
    asset("BepInEx_macos_universal_5.4.23.5.zip", 658168),
    asset("BepInEx_Patcher_5.4.23.5.zip", 8628),
    asset("BepInEx_win_x64_5.4.23.5.zip", 639118),
    asset("BepInEx_win_x86_5.4.23.5.zip", 638544),
]

chosen = pick_release_asset(
    bepinex_assets, platform_name="Windows", architecture="AMD64"
)
assert chosen["name"] == "BepInEx_win_x64_5.4.23.5.zip"

neutral_assets = [
    asset("CoolMod.zip", 2000),
    asset("CoolMod-debug.zip", 9000),
    asset("Source.zip", 10000),
]
chosen = pick_release_asset(
    neutral_assets, platform_name="Windows", architecture="AMD64"
)
assert chosen["name"] == "CoolMod.zip"

linux_only = [
    asset("Tool_linux_x64.zip", 2000),
]
assert pick_release_asset(
    linux_only, platform_name="Windows", architecture="AMD64"
) is None


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({
            "tag_name": "v5.4.23.5",
            "published_at": "2026-02-08T01:03:00Z",
            "assets": bepinex_assets,
        }).encode("utf-8")


with patch("urllib.request.urlopen", return_value=Response()):
    resolved = _resolve_github_release_url(
        "https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.5"
    )
assert resolved["name"] == "BepInEx_win_x64_5.4.23.5.zip"
assert resolved["asset_size"] == 639118
assert resolved["detail_verified"] is True
assert resolved["verification_source"] == "github_release_api"

with patch("urllib.request.urlopen", return_value=Response()):
    direct = _resolve_github_release_url(
        "https://github.com/BepInEx/BepInEx/releases/download/"
        "v5.4.23.5/BepInEx_win_x64_5.4.23.5.zip"
    )
assert direct["name"] == "BepInEx_win_x64_5.4.23.5.zip"
assert direct["url"] == "https://example.invalid/BepInEx_win_x64_5.4.23.5.zip"
assert "同名资产" in direct["note"]

with patch("urllib.request.urlopen", return_value=Response()):
    stale = _resolve_github_release_url(
        "https://github.com/BepInEx/BepInEx/releases/download/"
        "v5.4.23.5/asset-that-never-existed.zip"
    )
assert "error" in stale
assert "未自动替换" in stale["error"]

print("ALL PASS")
