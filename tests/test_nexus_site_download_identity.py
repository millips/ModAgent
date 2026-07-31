"""Nexus site tools resolve a real game_id and do not use zero."""
import asyncio
import json
import types

from modagent import downloader, nexus, tools


original_resolve = nexus.resolve_game_id
original_download = downloader.download_mod
calls = []


async def fake_download_mod(**kwargs):
    calls.append(kwargs)
    return {
        "mod_id": kwargs["mod_id"],
        "local_path": "",
        "mod_name": "Fluffy Mod Manager",
        "version": "3.079",
        "cached": False,
    }


try:
    nexus.resolve_game_id = lambda slug, key: 2295 if slug == "site" else 0
    downloader.download_mod = fake_download_mod
    cfg = types.SimpleNamespace(
        nexus_api_key="nexus", tavily_api_key="tavily",
        game_slug="streetfighter6", game_id=0,
        game_name="Street Fighter 6", game_root="X:/SF6",
        tier="free", chrome_cdp_port=18888,
    )
    # Download permission is normally tier-gated; use the paid tier in this
    # focused transport test.
    cfg.tier = "pro"
    result = json.loads(tools.execute(
        "mod_download",
        {"mod_id": 818, "file_id": 3458, "nexus_slug": "site"},
        cfg,
    ))
    assert "error" not in result
    assert calls[0]["game_slug"] == "site"
    assert calls[0]["game_id"] == 2295
finally:
    nexus.resolve_game_id = original_resolve
    downloader.download_mod = original_download


async def fake_signed_in_gate(**_kwargs):
    raise downloader.NexusManualDownloadRequired(
        "https://www.nexusmods.com/site/mods/818?tab=files",
        "（已自动尝试 Files → Manual Download → Slow Download，但页面尚未产生下载链接）",
    )


try:
    nexus.resolve_game_id = lambda slug, key: 2295 if slug == "site" else 0
    downloader.download_mod = fake_signed_in_gate
    gate_result = json.loads(tools.execute(
        "mod_download",
        {"mod_id": 818, "file_id": 3458, "nexus_slug": "site"},
        cfg,
    ))
    assert gate_result["status"] == "retryable_automation_error"
    assert gate_result["login_status"] == "signed_in_or_not_required"
    assert gate_result["user_action_required"] is False
    assert gate_result["automatic_retry_allowed"] is True
finally:
    nexus.resolve_game_id = original_resolve
    downloader.download_mod = original_download


async def verify_single_page_attempt():
    original_page = downloader.get_download_url_filepage
    attempts = []

    async def fail_once(*args, **kwargs):
        attempts.append((args, kwargs))
        raise RuntimeError("未获取到下载链接(原始返回: [])")

    try:
        downloader.get_download_url_filepage = fail_once
        try:
            await downloader.download_mod(
                818, "site", 2295, "key", file_id=3458
            )
        except RuntimeError:
            pass
        assert len(attempts) == 1
    finally:
        downloader.get_download_url_filepage = original_page


# Bypass preflight and metadata network calls for the retry-behaviour check.
original_preflight = downloader.preflight_check
original_info = downloader.get_mod_info
original_direct = downloader.get_download_url_api
try:
    downloader.preflight_check = lambda *args: "ws"
    downloader.get_mod_info = lambda *args: {
        "name": "Fluffy Mod Manager", "version": "3.079"
    }
    downloader.get_download_url_api = lambda *args: (_ for _ in ()).throw(
        downloader.NexusDirectDownloadUnavailable(
            "free account", {"http_status": 403}
        )
    )
    asyncio.run(verify_single_page_attempt())
finally:
    downloader.preflight_check = original_preflight
    downloader.get_mod_info = original_info
    downloader.get_download_url_api = original_direct

print("ALL PASS")
