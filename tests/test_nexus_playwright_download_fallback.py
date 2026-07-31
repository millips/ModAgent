"""A visible Nexus control must not be handed to the user when CDP misses it."""
import asyncio
import os
import tempfile

from modagent import downloader, playwright_driver


async def verify():
    original_eval = downloader._cdp_eval
    original_click = downloader._cdp_trusted_click
    original_sleep = asyncio.sleep
    original_fallback = playwright_driver.click_download_control
    original_downloads = downloader.DOWNLOADS_DIR
    root = tempfile.mkdtemp(prefix="ma-pw-fallback-")

    async def fake_eval(_ws, expr, _msg_id, **_kwargs):
        if "__modAgentDownloadCaptureInstalled" in expr:
            return True
        if expr == "window.__modAgentDownloadUrl || ''":
            return ""
        if "const fid =" in expr:
            return {
                "ready_to_click": True,
                "stage": "slow",
                "text": "Slow download",
                "x": 10, "y": 20,
                "url": "https://www.nexusmods.com/game/mods/4?tab=files",
            }
        return ""

    async def missed_click(*_args, **_kwargs):
        return False

    async def no_sleep(_seconds):
        return None

    def successful_fallback(_port, _url, _stage, capture_dir, _file_id=0):
        path = os.path.join(capture_dir, "mod.zip")
        os.makedirs(capture_dir, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"PK-test")
        return {"status": "clicked", "clicked": True, "downloads": [path]}

    try:
        downloader.DOWNLOADS_DIR = root
        downloader._cdp_eval = fake_eval
        downloader._cdp_trusted_click = missed_click
        asyncio.sleep = no_sleep
        playwright_driver.click_download_control = successful_fallback
        result = await downloader._nexus_automate_slow_download(
            object(), 9565, cdp_port=18888,
        )
        assert result["stage"] == "browser-download"
        assert result["local_path"].endswith("mod.zip")
    finally:
        downloader.DOWNLOADS_DIR = original_downloads
        downloader._cdp_eval = original_eval
        downloader._cdp_trusted_click = original_click
        asyncio.sleep = original_sleep
        playwright_driver.click_download_control = original_fallback


asyncio.run(verify())
print("ALL PASS")
