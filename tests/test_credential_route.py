"""No network or actual credentials: route/secret bundles and API edits."""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MODAGENT_DATA_DIR", tempfile.mkdtemp(prefix="modagent-credential-route-"))
from modagent import config


def test_bound_bundle(monkeypatch, tmp_path):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({"llm_endpoint": "https://old.example/v1", "llm_model": "old", "llm_api_key": "stale"}))
    monkeypatch.setattr(config, "CONFIG_FILE", str(file))
    monkeypatch.setenv("MODAGENT_CREDENTIAL_ROUTE", "1")
    monkeypatch.setenv("MODAGENT_LLM_ENDPOINT", "https://new.example/v1")
    monkeypatch.setenv("MODAGENT_LLM_MODEL", "new")
    monkeypatch.setenv("MODAGENT_LLM_API_KEY", "bound-fake-key")
    loaded = config.load()
    assert (loaded.llm_endpoint, loaded.llm_model, loaded.llm_api_key) == ("https://new.example/v1", "new", "bound-fake-key")
    monkeypatch.setenv("MODAGENT_LLM_API_KEY", "")
    assert config.load().llm_api_key == ""


def test_endpoint_edit_clears_old_key(monkeypatch):
    from modagent import api
    cfg = config.Config(llm_endpoint="https://old.example/v1", llm_api_key="old-fake-key")
    monkeypatch.setattr(api, "cfg", cfg)
    monkeypatch.setattr(api, "save_config", lambda value: None)
    monkeypatch.setattr(api, "agents", {})
    monkeypatch.setenv("MODAGENT_CREDENTIAL_ROUTE", "1")
    api.update_config(api.ConfigUpdate(llm_endpoint="https://new.example/v1"))
    assert cfg.llm_api_key == ""
    assert os.environ["MODAGENT_LLM_API_KEY"] == ""
    api.update_config(api.ConfigUpdate(llm_endpoint="https://new.example/v1", llm_api_key="new-fake-key"))
    assert cfg.llm_api_key == "new-fake-key"
    api.update_config(api.ConfigUpdate(llm_endpoint="https://new.example/v1/", llm_model="other-model"))
    assert cfg.llm_api_key == "new-fake-key"
