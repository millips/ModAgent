"""Diagnostic turns are read-only and session IDs do not collide by second."""
import json

from modagent.agent import Agent, is_diagnostic_read_only_request
from modagent.api import _new_session_id


class Config:
    tier = "pro"
    dev_mode = False


assert is_diagnostic_read_only_request("额 现在游戏里怎么一个怪都没有？")
assert is_diagnostic_read_only_request("帮我检查哪些模组不生效")
assert is_diagnostic_read_only_request("按了之后没有黄色描边，仅有扫描动画")
assert not is_diagnostic_read_only_request("帮我禁用 BetterMap")
assert not is_diagnostic_read_only_request("直接修复这个问题")

agent = Agent(Config())
agent._diagnostic_read_only_turn = True
blocked = json.loads(agent._exec("mod_disable", {"mod_id": "MoreHead"}))
assert blocked["error"] == "diagnostic_scope_change_blocked"

first = _new_session_id()
second = _new_session_id()
assert first != second
assert first.startswith("session_") and second.startswith("session_")

print("DIAGNOSTIC SESSION ISOLATION TESTS PASSED")
