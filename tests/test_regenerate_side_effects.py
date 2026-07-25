"""Regeneration rewrites text without replaying mutating tools."""
import json

from modagent import agent as agent_module
from modagent.agent import Agent, REGENERATE_BLOCKED_TOOLS


class Config:
    tier = "pro"
    dev_mode = False


class FakeAgent(Agent):
    def __init__(self):
        super().__init__(Config())
        self.seen_tools = []
        self.seen_messages = []

    def _stream(self, messages, tools):
        self.seen_messages = list(messages)
        self.seen_tools = [
            tool["function"]["name"] for tool in tools
        ]
        return [type("Chunk", (), {
            "choices": [type("Choice", (), {
                "delta": type("Delta", (), {
                    "content": "这是基于当前状态重写的回答。",
                    "tool_calls": None,
                })(),
            })()],
        })()]


old_prompt = agent_module.build_prompt
old_tools = agent_module.build_tools_definitions
agent_module.build_prompt = lambda _cfg: "system"
agent_module.build_tools_definitions = lambda _tier: [
    {"type": "function", "function": {"name": "get_installed"}},
    {"type": "function", "function": {"name": "mod_download"}},
    {"type": "function", "function": {"name": "snapshot_create"}},
    {"type": "function", "function": {"name": "browser_click"}},
]

try:
    instance = FakeAgent()
    events = [
        json.loads(item) for item in instance.chat_stream(
            "安装这个 Mod",
            regenerate=True,
            completed_effects=["mod_download 已完成", "mod_install 已完成"],
        )
    ]
    assert instance.seen_tools == ["get_installed"]
    assert all(name not in instance.seen_tools for name in REGENERATE_BLOCKED_TOOLS)
    guard = next(
        message["content"] for message in instance.seen_messages
        if message["role"] == "system" and "重新生成" in message["content"]
    )
    assert "严禁再次下载" in guard
    assert "mod_install 已完成" in guard
    assert any(event.get("done") is True for event in events)

    instance._regenerating = True
    blocked = json.loads(instance._exec("mod_download", {"mod_id": 1}))
    assert blocked["error"] == "regenerate_side_effect_blocked"
finally:
    agent_module.build_prompt = old_prompt
    agent_module.build_tools_definitions = old_tools

print("ALL PASS")
