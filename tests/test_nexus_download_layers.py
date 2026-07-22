"""Nexus direct API and Shadow DOM website fallbacks report exact outcomes."""
import asyncio
import io
import urllib.error

from modagent import downloader, web_agent


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'[{"URI":"https://cf-files.nexusmods.com/file.zip?token=secret"}]'


original_urlopen = downloader.urllib.request.urlopen
try:
    downloader.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
    direct = downloader.get_download_url_api("game", 10, 20, "key")
    assert direct.startswith("https://cf-files.nexusmods.com/")

    def forbidden(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.nexusmods.com/download_link.json",
            403,
            "Forbidden",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"message":"Premium or website flow required"}'),
        )

    downloader.urllib.request.urlopen = forbidden
    try:
        downloader.get_download_url_api("game", 10, 20, "key")
        raise AssertionError("403 should not return a URL")
    except downloader.NexusDirectDownloadUnavailable as exc:
        assert exc.diagnostics["http_status"] == 403
        assert exc.diagnostics["premium_or_site_flow_required"] is True
        assert "Premium" in exc.diagnostics["message"]
finally:
    downloader.urllib.request.urlopen = original_urlopen


async def verify_shadow_site_error():
    original_eval = downloader._cdp_eval
    original_click = downloader._cdp_trusted_click
    original_sleep = asyncio.sleep
    clicked = {"slow": False}

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
                "x": 12,
                "y": 34,
                "siteDownloadError": "ERROR-download-location-not-found",
                "loggedIn": True,
            }
        return ""

    async def fake_click(*_args, **_kwargs):
        clicked["slow"] = True
        return True

    async def no_sleep(_seconds):
        return None

    try:
        downloader._cdp_eval = fake_eval
        downloader._cdp_trusted_click = fake_click
        asyncio.sleep = no_sleep
        result = await downloader._nexus_automate_slow_download(object(), 20)
        assert clicked["slow"] is True
        assert result["stage"] == "site-download-error"
        assert result["state"]["loggedIn"] is True
    finally:
        downloader._cdp_eval = original_eval
        downloader._cdp_trusted_click = original_click
        asyncio.sleep = original_sleep


asyncio.run(verify_shadow_site_error())
assert "shadowRoot" in web_agent._OBSERVE_SCRIPT
assert "deepElements" in web_agent._OBSERVE_SCRIPT
print("ALL PASS")
