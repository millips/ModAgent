"""Search fallback rejects default browse noise and stops runaway retries."""
import json
import time

from modagent.agent import Agent, SEARCH_TURN_MAX_CALLS
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
agent._turn_started_monotonic = time.monotonic()
agent._turn_search_calls = SEARCH_TURN_MAX_CALLS
blocked = json.loads(agent._exec("nexus_search", {"query": "another retry"}))
assert blocked["error"] == "search_budget_exhausted"
assert blocked["search_calls"] == SEARCH_TURN_MAX_CALLS

print("ALL PASS")
