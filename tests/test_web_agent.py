"""Standalone tests for the semantic browser tool layer."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modagent import web_agent


assert web_agent._allowed_url("https://www.nexusmods.com/game/mods/1")
assert web_agent._allowed_url("https://github.com/example/repo")
assert not web_agent._allowed_url("file:///C:/Windows/System32")
assert not web_agent._allowed_url("https://nexusmods.com.evil.example/")

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

print("ALL PASS")
