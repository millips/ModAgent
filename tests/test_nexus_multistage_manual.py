"""Nexus page Manual -> dialog Manual -> Slow is one adaptive flow."""

import asyncio

from modagent import downloader


async def verify():
    original_eval = downloader._cdp_eval
    original_click = downloader._cdp_trusted_click
    original_navigate = downloader._cdp_navigate
    original_sleep = asyncio.sleep
    state = {"step": 0, "hooked": False}
    navigated = []
    clicked = []

    async def fake_eval(_ws, expr, _msg_id, **_kwargs):
        if "__modAgentDownloadCaptureInstalled" in expr:
            state["hooked"] = True
            return True
        if expr == "window.__modAgentDownloadUrl || ''":
            if state["step"] == 3 and state["hooked"]:
                return "https://cf-files.nexusmods.com/multistage.zip"
            return ""
        if "const fid =" in expr:
            if state["step"] == 0:
                return {
                    "ready_to_click": True,
                    "stage": "manual",
                    "text": "Manual",
                    "href": "https://www.nexusmods.com/game/mods/125?tab=files",
                    "url": "https://www.nexusmods.com/game/mods/125?tab=files",
                }
            if state["step"] == 1:
                return {
                    "ready_to_click": True,
                    "stage": "manual",
                    "text": "Manual download",
                    "href": "https://www.nexusmods.com/api/files/123/download",
                    "url": "https://www.nexusmods.com/game/mods/125?tab=files",
                }
            return {
                "ready_to_click": True,
                "stage": "slow",
                "text": "Slow download",
                "x": 30,
                "y": 40,
                "url": "https://www.nexusmods.com/api/files/123/download",
            }
        return ""

    async def fake_navigate(_ws, url, _msg_id, **_kwargs):
        navigated.append(url)
        state["step"] += 1
        state["hooked"] = False
        return True

    async def fake_click(*_args, **_kwargs):
        clicked.append(state["step"])
        state["step"] += 1
        return True

    async def no_sleep(_seconds):
        return None

    try:
        downloader._cdp_eval = fake_eval
        downloader._cdp_navigate = fake_navigate
        downloader._cdp_trusted_click = fake_click
        asyncio.sleep = no_sleep
        result = await downloader._nexus_automate_slow_download(object(), 123)
        assert result["stage"] == "captured"
        assert result["url"].endswith("multistage.zip")
        assert navigated == []
        assert clicked == [0, 1, 2]
    finally:
        downloader._cdp_eval = original_eval
        downloader._cdp_navigate = original_navigate
        downloader._cdp_trusted_click = original_click
        asyncio.sleep = original_sleep


asyncio.run(verify())
print("ALL PASS")
