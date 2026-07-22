"""The Nexus capture hook survives Manual -> Slow page navigation."""
import asyncio

from modagent import downloader


async def verify():
    original_eval = downloader._cdp_eval
    original_click = downloader._cdp_trusted_click
    original_sleep = asyncio.sleep
    calls = []
    document = {"generation": 0, "hooked": False, "pending_stage": ""}

    async def fake_eval(ws, expr, msg_id, await_promise=False, timeout=25):
        calls.append(expr)
        if "__modAgentDownloadCaptureInstalled" in expr:
            document["hooked"] = True
            return True
        if expr == "window.__modAgentDownloadUrl || ''":
            if document["pending_stage"] == "slow-clicked" and document["hooked"]:
                return "https://cf-files.nexusmods.com/test.zip"
            return ""
        if "const fid =" in expr:
            if document["generation"] == 0:
                document["pending_stage"] = "files"
                return {
                    "ready_to_click": True, "stage": "files",
                    "text": "FILES 2", "x": 5, "y": 10,
                }
            if document["generation"] == 1:
                document["pending_stage"] = "manual"
                return {
                    "ready_to_click": True, "stage": "manual",
                    "text": "Manual Download", "x": 10, "y": 20,
                }
            document["pending_stage"] = "slow"
            return {
                "ready_to_click": True, "stage": "slow",
                "text": "Slow download", "x": 30, "y": 40,
            }
        return ""

    async def fake_click(ws, x, y, msg_id, timeout=10):
        if document["pending_stage"] == "files":
            document["generation"] = 1
            document["hooked"] = False
            document["pending_stage"] = "files-clicked"
        elif document["pending_stage"] == "manual":
            # Manual Download replaces the document and destroys injected JS.
            document["generation"] = 2
            document["hooked"] = False
            document["pending_stage"] = "manual-clicked"
        elif document["pending_stage"] == "slow":
            document["pending_stage"] = "slow-clicked"
        return True

    async def no_sleep(_seconds):
        return None

    try:
        downloader._cdp_eval = fake_eval
        downloader._cdp_trusted_click = fake_click
        asyncio.sleep = no_sleep
        result = await downloader._nexus_automate_slow_download(object(), 9565)
        assert result["url"] == "https://cf-files.nexusmods.com/test.zip"
        assert result["stage"] == "captured"
        assert sum("__modAgentDownloadCaptureInstalled" in c for c in calls) >= 4
        page_url = downloader._nexus_files_page_url(
            "finalfantasy7rebirth", 816
        )
        assert page_url.endswith("/mods/816?tab=files")
        assert "file_id=" not in page_url
        assert "尚未登录" not in downloader._nexus_gate_reason({
            "loggedIn": True,
            "login": True,
        })
    finally:
        downloader._cdp_eval = original_eval
        downloader._cdp_trusted_click = original_click
        asyncio.sleep = original_sleep


asyncio.run(verify())
print("ALL PASS")
