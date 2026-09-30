"""Search fallback rejects browse noise and keeps discovery bounded per turn."""
import json
from unittest.mock import patch

from modagent.agent import Agent
from modagent.config import Config
from modagent.downloader import _filter_cdp_search_results


default_rows = [
    {"mod_id": 23, "name": "Shared Upgrades - Comestic Update"},
    {"mod_id": 13, "name": "(Outdated) Enemy Location"},
    {"mod_id": 4, "name": "R.E.P.O Infinite Sprint"},
]

assert _filter_cdp_search_results("BetterMap", default_rows) == []
assert [
    row["mod_id"]
    for row in _filter_cdp_search_results("enemy map location", default_rows)
] == [13]
assert len(_filter_cdp_search_results("latest popular trending mods", default_rows)) == 3

agent = Agent(Config())
with patch("modagent.agent.execute", return_value=json.dumps({"results": []})) as execute:
    for index in range(4):
        result = json.loads(agent._exec("nexus_search", {"query": f"retry {index}"}))
        assert "error" not in result

    repeated = json.loads(agent._exec("nexus_search", {"query": "retry 0"}))
    assert repeated["reused_result"] is True
    assert repeated["searched"] is False

    blocked = json.loads(agent._exec("nexus_search", {"query": "one more alias"}))
    assert blocked["status"] == "search_source_budget_exhausted"
    assert execute.call_count == 4

assert agent._turn_search_calls == 4

print("ALL PASS")
