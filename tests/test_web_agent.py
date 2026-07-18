"""Standalone tests for the semantic browser tool layer."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modagent import web_agent


assert web_agent._allowed_url("https://www.nexusmods.com/game/mods/1")
assert web_agent._allowed_url("https://github.com/example/repo")
assert web_agent._allowed_url("https://www.moddb.com/mods/example")
assert web_agent._allowed_url("https://www.fluffyquack.com/tools/modmanager")
assert not web_agent._allowed_url("file:///C:/Windows/System32")
assert not web_agent._allowed_url("https://nexusmods.com.evil.example/")
assert "__modAgentDownloadCaptureInstalled" in web_agent._OBSERVE_SCRIPT
assert "GenerateDownloadUrl" in web_agent._OBSERVE_SCRIPT
assert "__modAgentObservationId" in web_agent._OBSERVE_SCRIPT

fake_tab = {
    "id": "tab-1",
    "type": "page",
    "title": "Example",
    "url": "https://www.nexusmods.com/game/mods/1",
    "webSocketDebuggerUrl": "ws://example",
}
fake_snapshot = {
    "status": "ok",
    "url": fake_tab["url"],
    "title": "Example",
    "controls": [{"target_id": "ma-1", "kind": "button", "text": "Manual"}],
}

with patch.object(web_agent, "_select_tab", return_value=fake_tab), \
     patch.object(web_agent, "_evaluate", new=AsyncMock(return_value=fake_snapshot)):
    observed = web_agent.observe(18888)
    assert observed["tab_id"] == "tab-1"
    assert observed["controls"][0]["text"] == "Manual"

with patch.object(web_agent, "_tabs", return_value=[fake_tab]):
    pages = web_agent.list_pages(18888)
    assert pages["status"] == "ok"
    assert pages["pages"][0]["tab_id"] == "tab-1"

new_tab = {
    **fake_tab,
    "id": "tab-2",
    "url": "https://www.nexusmods.com/game/mods/1?tab=files",
}
with patch.object(web_agent, "_select_tab", return_value=fake_tab), \
     patch.object(web_agent, "_native_click", new=AsyncMock(return_value={"status": "clicked"})), \
     patch.object(web_agent, "_tabs", side_effect=[[fake_tab], [fake_tab, new_tab]]), \
     patch.object(web_agent, "observe", return_value={"status": "ok", "tab_id": "tab-2"}) as observe_mock, \
     patch.object(web_agent.time, "sleep"):
    clicked = web_agent.click(18888, "ma-1", "tab-1")
    assert clicked["page"]["tab_id"] == "tab-2"
    observe_mock.assert_called_once_with(18888, "tab-2")

with patch.object(web_agent, "_tabs", return_value=[fake_tab]), \
     patch.object(web_agent, "observe", return_value={"status": "ok", "tab_id": "tab-1"}), \
     patch.object(web_agent.urllib.request, "urlopen") as open_mock:
    reused = web_agent.open_page(18888, fake_tab["url"] + "#files")
    assert reused["reused_tab"] is True
    open_mock.assert_not_called()

print("ALL PASS")
