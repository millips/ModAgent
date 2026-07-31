"""Installed-Mod update turns never drift into new-Mod recommendation tools."""
import json

from modagent import agent as agent_module
from modagent.agent import Agent, SEARCH_DISCOVERY_TOOLS, is_update_request


class Config:
    tier = "pro"
    dev_mode = False


def chunk(content=None, tool_calls=None):
    delta = type("Delta", (), {
        "content": content,
        "tool_calls": tool_calls,
    })()
    choice = type("Choice", (), {"delta": delta})()
    return type("Chunk", (), {"choices": [choice]})()


class UpdateAgent(Agent):
    def _stream(self, _messages, tools):
        names = {
            tool.get("function", {}).get("name")
            for tool in tools
        }
        assert not names.intersection(SEARCH_DISCOVERY_TOOLS)
        return [chunk(content="已按本机安装清单完成更新检查。")]


assert is_update_request("帮我更新已有 Mod")
assert is_update_request("检查更新")
assert is_update_request("帮我把所有 Mod 都更新到最新版")
assert is_update_request("把这些模组升级一下")
assert not is_update_request("推荐几个最近更新的热门 Mod")

old_prompt = agent_module.build_prompt
old_tools = agent_module.build_tools_definitions
old_report = agent_module.ENABLE_REPORT_VALIDATION
old_state = agent_module.ENABLE_STATE_CHECK
agent_module.build_prompt = lambda _cfg: "system"
agent_module.build_tools_definitions = lambda _tier: [
    {"type": "function", "function": {"name": "mod_update_check"}},
    {"type": "function", "function": {"name": "mod_update"}},
    {"type": "function", "function": {"name": "mod_recommend"}},
    {"type": "function", "function": {"name": "nexus_search"}},
]
agent_module.ENABLE_REPORT_VALIDATION = False
agent_module.ENABLE_STATE_CHECK = False

try:
    events = [
        json.loads(value)
        for value in UpdateAgent(Config()).chat_stream("帮我更新已有 Mod")
    ]
    assert not any(event.get("recommendations") for event in events)
    assert "更新检查" in "".join(event.get("chunk", "") for event in events)

    direct = UpdateAgent(Config())
    direct._update_intent = True
    blocked = json.loads(direct._exec("mod_recommend", {"query": "new mods"}))
    assert blocked["error"] == "update_search_scope_blocked"
finally:
    agent_module.build_prompt = old_prompt
    agent_module.build_tools_definitions = old_tools
    agent_module.ENABLE_REPORT_VALIDATION = old_report
    agent_module.ENABLE_STATE_CHECK = old_state

print("UPDATE INTENT SCOPE TESTS PASSED")
