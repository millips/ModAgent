"""Final structured recommendation SSE is shared by Free and Pro."""
import json
import os

from modagent import agent as agent_module
from modagent.agent import Agent
from modagent.recommendation_ui import apply_chinese_descriptions


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


tool_call = type("ToolCall", (), {
    "index": 0,
    "id": "recommend-1",
    "function": type("Function", (), {
        "name": "mod_recommend",
        "arguments": '{"query":"costumes"}',
    })(),
})()


class FakeAgent(Agent):
    def __init__(self, tier="pro"):
        cfg = Config()
        cfg.tier = tier
        super().__init__(cfg)
        self.round = 0

    def _stream(self, _messages, _tools):
        self.round += 1
        if self.round == 1:
            return [chunk(tool_calls=[tool_call])]
        return [chunk(
            content=(
                "## 推荐分析\n"
                "| # | Mod | 版本 |\n|---|---|---|\n| 1 | One | 1.0 |\n"
                "- **One**：维护较活跃，适合作为首选。\n"
                "- **Two**：可以作为备选，安装前仍需核验依赖与冲突。"
            ),
            tool_calls=None,
        )]

    def _exec(self, _name, _args):
        return json.dumps({
            "recommendations": [
                {"mod_id": 1, "name": "One", "summary": "Adds the first feature."},
                {"mod_id": 2, "name": "Two", "summary": "Adds the second feature."},
            ],
        })

    def _localize_recommendation_set(self, payload):
        return apply_chinese_descriptions(payload, {
            "items": [
                {
                    "selection_key": item["selection_key"],
                    "content": f"{item['name']} 的中文功能介绍。",
                }
                for item in payload["items"]
            ],
        })


old_prompt = agent_module.build_prompt
old_tools = agent_module.build_tools_definitions
old_report = agent_module.ENABLE_REPORT_VALIDATION
old_state = agent_module.ENABLE_STATE_CHECK
old_edition = os.environ.get("MODAGENT_EDITION")
agent_module.build_prompt = lambda _cfg: "system"
agent_module.build_tools_definitions = lambda _tier: [
    {"type": "function", "function": {"name": "mod_recommend"}}
]
agent_module.ENABLE_REPORT_VALIDATION = False
agent_module.ENABLE_STATE_CHECK = False

try:
    os.environ["MODAGENT_EDITION"] = "subscription"
    pro_events = [json.loads(value) for value in FakeAgent().chat_stream("recommend")]
    recommendation_events = [event for event in pro_events if "recommendations" in event]
    assert len(recommendation_events) == 1
    assert len(recommendation_events[0]["recommendations"]["items"]) == 2
    narrative = "\n".join(event.get("chunk", "") for event in pro_events)
    assert "1. **One**" in narrative
    assert "2. **Two**" in narrative
    assert "One 的中文功能介绍" in narrative
    assert "Two 的中文功能介绍" in narrative
    assert not any("| 1 | One |" in event.get("chunk", "") for event in pro_events)
    assert all(
        "中文功能介绍" in item["content"]
        for item in recommendation_events[0]["recommendations"]["items"]
    )

    os.environ["MODAGENT_EDITION"] = "free"
    free_events = [json.loads(value) for value in FakeAgent("free").chat_stream("recommend")]
    free_recommendations = [event for event in free_events if "recommendations" in event]
    assert len(free_recommendations) == 1
    assert len(free_recommendations[0]["recommendations"]["items"]) == 2
finally:
    agent_module.build_prompt = old_prompt
    agent_module.build_tools_definitions = old_tools
    agent_module.ENABLE_REPORT_VALIDATION = old_report
    agent_module.ENABLE_STATE_CHECK = old_state
    if old_edition is None:
        os.environ.pop("MODAGENT_EDITION", None)
    else:
        os.environ["MODAGENT_EDITION"] = old_edition

print("ALL PASS")
