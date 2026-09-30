"""Synthetic secrets only; invalid credentials must fail before HTTP or saves."""
import pytest

from modagent import networking


@pytest.mark.parametrize("value", ["中文占位密钥", "fake\nkey", "fake key", "fake\x00key", "fake\x7fkey"])
def test_invalid_key_has_safe_field_error(value):
    with pytest.raises(ValueError) as error:
        networking.validate_api_key(value, "llm_api_key")
    assert str(error.value) == "credential_llm_api_key_invalid"
    assert value not in networking.friendly_network_error(error.value)


@pytest.mark.parametrize("value", ["", "local-token", "abc+/=_-.123", "  fake-key  "])
def test_ascii_tokens_are_not_provider_specific(value):
    assert networking.validate_api_key(value, "llm_api_key") == value.strip()


def test_preflight_blocks_legacy_key_before_client_creation(monkeypatch):
    from modagent.agent import Agent
    from modagent.config import Config
    def forbidden(*args, **kwargs):
        pytest.fail("HTTP client must not be created for invalid credentials")
    monkeypatch.setattr(networking, "build_http_client", forbidden)
    instance = Agent(Config(llm_api_key="中文占位密钥"))
    with pytest.raises(ValueError, match="credential_llm_api_key_invalid"):
        _ = instance.client


def test_api_rejects_entire_edit_before_mutation(monkeypatch):
    from modagent import api
    from modagent.config import Config
    cfg = Config(llm_api_key="existing-fake", llm_model="original")
    monkeypatch.setattr(api, "cfg", cfg)
    monkeypatch.setattr(api, "save_config", lambda *a: pytest.fail("must not save"))
    with pytest.raises(api.HTTPException) as error:
        api.update_config(api.ConfigUpdate(llm_model="changed", llm_api_key="中文占位密钥"))
    assert error.value.status_code == 400
    assert error.value.detail == "credential_llm_api_key_invalid"
    assert cfg.llm_model == "original" and cfg.llm_api_key == "existing-fake"


def test_encoding_error_is_not_network_advice():
    error = UnicodeEncodeError("ascii", "synthetic-中文", 10, 12, "ordinal not in range")
    message, retryable = networking.model_failure_summary(error)
    assert not retryable
    assert "编码" in message and "检查网络" not in message
    assert "synthetic" not in message


def test_bad_key_summary_names_field_not_secret():
    error = networking.CredentialFormatError("llm_api_key")
    message, retryable = networking.model_failure_summary(error)
    assert not retryable and "LLM API Key" in message
    assert "检查网络" not in message


def test_streamed_invalid_key_has_failed_nonretryable_result(monkeypatch, tmp_path):
    import json
    from modagent import db
    from modagent.agent import Agent
    from modagent.config import Config
    from modagent.orchestration import store
    from modagent.orchestration.models import AgentMode, TaskSpec
    from modagent.orchestration.runtime import AgentCoreRuntime
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "format.db"))
    db.init_db()
    spec = TaskSpec.create(session_id="format", game_id="fixture",
                           intent=AgentMode.CHAT_EXPLAIN, user_goal="mod是什么")
    runtime = AgentCoreRuntime(spec, feature_mode="on")
    runtime.start()
    agent = Agent(Config(llm_api_key="中文占位密钥"))
    monkeypatch.setattr(networking, "build_http_client", lambda *a, **k: pytest.fail("HTTP not allowed"))
    events = [json.loads(event) for event in agent.chat_stream(
        "mod是什么", task_spec=spec, core_runtime=runtime, core_mode="on")]
    task = store.get_task(spec.task_id)
    assert task["state"] == "FAILED"
    assert task["outcome"]["retryable"] is False
    text = "".join(event.get("chunk", "") for event in events)
    assert "LLM API Key" in text and "检查网络" not in text
    assert "中文占位密钥" not in json.dumps(events, ensure_ascii=False)
