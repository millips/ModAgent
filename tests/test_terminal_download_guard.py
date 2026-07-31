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
