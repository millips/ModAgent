import json

from modagent import agent as agent_module
from modagent.agent import Agent
from modagent.config import Config


def _terminal_failure(tool: str) -> str:
    return json.dumps({
        "error": "download_failed",
        "status": "download_failed_terminal",
        "tool": tool,
        "message": "下载地址不存在或已失效（HTTP 404），未继续重试。",
        "terminal": True,
        "retryable": False,
        "automatic_retry_allowed": False,
        "stop_further_downloads": True,
        "continue_other_items": False,
        "http_status": 404,
    }, ensure_ascii=False)


def _manual_gate() -> str:
    return json.dumps({
        "error": "manual_download_required",
        "status": "manual_action_required",
        "mod_id": "2937",
        "file_id": "7327",
        "nexus_slug": "streetfighter6",
        "page_url": "https://www.nexusmods.com/streetfighter6/mods/2937",
        "user_action_required": "请在已保留的 Nexus 页面完成人机验证。",
        "automatic_retry_allowed": False,
        "stop_further_downloads": False,
        "continue_other_items": True,
    }, ensure_ascii=False)


def test_same_terminal_download_is_not_executed_twice(monkeypatch):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, args))
        return _terminal_failure(name)

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = Agent(Config())
    args = {"url": "https://example.invalid/missing.zip"}

    first = json.loads(instance._exec("download_from_url", args))
    second = json.loads(instance._exec("download_from_url", args))

    assert first["status"] == "download_failed_terminal"
    assert second["reused_result"] is True
    assert len(calls) == 1


def test_explicit_target_failure_blocks_source_substitution(monkeypatch):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, args))
        return _terminal_failure(name)

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = Agent(Config())
    instance._explicit_install_target = {"name": "WantedMod", "version": ""}

    first = json.loads(instance._exec(
        "download_from_url",
        {"url": "https://example.invalid/missing.zip"},
    ))
    substituted = json.loads(instance._exec("mod_download", {"mod_id": 115}))

    assert first["status"] == "download_failed_terminal"
    assert substituted["error"] == "explicit_target_download_already_failed"
    assert substituted["automatic_retry_allowed"] is False
    assert len(calls) == 1


def test_failure_summary_keeps_actionable_http_context():
    payload = _terminal_failure("download_from_url")
    summary = Agent._tool_summary("download_from_url", payload, False)

    assert "HTTP 404" in summary
    assert "未继续重试" in summary


def test_manual_gate_is_waiting_state_not_red_failure():
    instance = Agent(Config())
    payload = _manual_gate()

    assert instance._is_error(payload) is False
    assert "等待 Nexus 人机验证" in instance._tool_summary(
        "mod_download", payload, True
    )
    message = instance._manual_download_action_message(payload)
    assert "下载已暂停" in message
    assert "完成了" in message
    assert "不会重新搜索、换源" in message


def test_manual_gate_target_is_recovered_from_history():
    instance = Agent(Config())
    instance.history = [{
        "role": "tool",
        "tool_call_id": "call-1",
        "content": _manual_gate(),
    }]

    assert instance._pending_manual_download_targets() == [{
        "mod_id": "2937",
        "file_id": "7327",
        "nexus_slug": "streetfighter6",
        "page_url": "https://www.nexusmods.com/streetfighter6/mods/2937",
    }]
    assert instance._is_manual_resume_request("完成了")


def test_manual_resume_forces_original_nexus_file(monkeypatch):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, args))
        return json.dumps({
            "mod_id": args["mod_id"],
            "local_path": "C:/tmp/mod.zip",
        })

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = Agent(Config())
    instance._manual_resume_turn = True
    instance._manual_resume_targets = [{
        "mod_id": "2937",
        "file_id": "7327",
        "nexus_slug": "streetfighter6",
        "page_url": "https://www.nexusmods.com/streetfighter6/mods/2937",
    }]

    result = json.loads(instance._exec(
        "mod_download", {"mod_id": "9999", "file_id": "8888"}
    ))

    assert result["mod_id"] == "2937"
    assert calls == [(
        "mod_download",
        {"mod_id": "2937", "file_id": "7327"},
    )]


def test_manual_resume_rejects_generic_downloader(monkeypatch):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, args))
        return "{}"

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = Agent(Config())
    instance._manual_resume_turn = True
    instance._manual_resume_targets = [{"mod_id": "2937", "file_id": "7327"}]

    result = json.loads(instance._exec(
        "download_from_url",
        {"url": "https://www.nexusmods.com/streetfighter6/mods/2937"},
    ))

    assert result["error"] == "manual_resume_scope_blocked"
    assert calls == []


def test_stream_pauses_for_manual_gate_then_resumes_exact_target(
    monkeypatch,
):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, dict(args)))
        if len(calls) == 1:
            return _manual_gate()
        return json.dumps({
            "status": "downloaded",
            "mod_id": args.get("mod_id"),
            "file_id": args.get("file_id"),
            "local_path": "C:/tmp/streetfighter6-2937-7327.zip",
        }, ensure_ascii=False)

    def chunk(content=None, tool_calls=None):
        delta = type("Delta", (), {
            "content": content,
            "tool_calls": tool_calls,
        })()
        choice = type("Choice", (), {"delta": delta})()
        return type("Chunk", (), {"choices": [choice]})()

    def tool_call(call_id, mod_id, file_id):
        return type("ToolCall", (), {
            "index": 0,
            "id": call_id,
            "function": type("Function", (), {
                "name": "mod_download",
                "arguments": json.dumps({
                    "mod_id": mod_id,
                    "file_id": file_id,
                }),
            })(),
        })()

    class ManualGateAgent(Agent):
        def __init__(self):
            super().__init__(Config())
            self.stream_round = 0

        def _stream(self, _messages, _tools):
            self.stream_round += 1
            if self.stream_round == 1:
                return [chunk(tool_calls=[
                    tool_call("first-download", "2937", "7327")
                ])]
            if self.stream_round == 2:
                # Deliberately imitate a bad model argument. The resume guard
                # must replace it with the exact target persisted in history.
                return [chunk(tool_calls=[
                    tool_call("resume-download", "9999", "8888")
                ])]
            return [chunk(content="原文件下载完成。")]

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    monkeypatch.setattr(agent_module, "build_prompt", lambda _cfg: "system")
    monkeypatch.setattr(
        agent_module,
        "build_tools_definitions",
        lambda _tier: [{
            "type": "function",
            "function": {"name": "mod_download"},
        }],
    )
    monkeypatch.setattr(agent_module, "ENABLE_REPORT_VALIDATION", False)
    monkeypatch.setattr(agent_module, "ENABLE_STATE_CHECK", False)

    instance = ManualGateAgent()
    first_events = [
        json.loads(item) for item in instance.chat_stream("下载这个 Mod")
    ]

    assert instance.stream_round == 1
    assert calls == [(
        "mod_download", {"mod_id": "2937", "file_id": "7327"}
    )]
    assert any(
        event.get("tool_result", {}).get("ok") is True
        and "等待 Nexus 人机验证"
        in event.get("tool_result", {}).get("summary", "")
        for event in first_events
    )
    assert any(
        "下载已暂停" in event.get("chunk", "")
        and "完成了" in event.get("chunk", "")
        for event in first_events
    )

    second_events = [
        json.loads(item) for item in instance.chat_stream("完成了")
    ]

    assert instance.stream_round == 3
    assert calls[-1] == (
        "mod_download", {"mod_id": "2937", "file_id": "7327"}
    )
    assert any(
        "原文件下载完成" in event.get("chunk", "")
        for event in second_events
    )
