"""Regression: recommendation resolution must never mutate or broaden scope."""

import json

from modagent.agent import Agent
from modagent.config import Config


agent = Agent(Config())
agent._selection_action = "resolve"
agent._selection_allowed_source_urls = {
    "https://gamebanana.com/mods/695582",
}


def check(label, value):
    assert value, label
    print("OK", label)


for tool_name, arguments in (
    ("gamebanana_search", {"query": "unrelated"}),
    ("download_from_url", {"url": "https://gamebanana.com/dl/1"}),
    ("mod_install", {"local_path": "C:/tmp/example.zip"}),
    ("snapshot_create", {}),
):
    result = json.loads(agent._exec(tool_name, arguments))
    check(f"{tool_name} blocked during resolve", result.get("error") == "resolution_scope_blocked")

wrong_page = json.loads(agent._exec("browser_open", {
    "url": "https://gamebanana.com/mods/999999",
}))
check("unselected source page blocked", wrong_page.get("error") == "resolution_source_scope_blocked")

print("RESOLUTION SCOPE GUARD PASSED")
