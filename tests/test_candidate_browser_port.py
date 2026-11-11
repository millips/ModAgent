import pytest
from modagent import config


def test_candidate_browser_port_does_not_change_saved_production_profile(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"chrome_cdp_port":18888,"agent_core_v2":"off"}', encoding="utf-8")
    before = config_file.read_bytes()
    monkeypatch.setattr(config, "CONFIG_FILE", str(config_file))
    monkeypatch.setenv("MODAGENT_CHROME_CDP_PORT", "19991")
    monkeypatch.setenv("MODAGENT_AGENT_CORE_V2", "on")
    loaded = config.load()
    assert loaded.chrome_cdp_port == 19991
    assert loaded.agent_core_v2 == "on"
    assert config_file.read_bytes() == before


@pytest.mark.parametrize("port", ["0", "65536", "bad"])
def test_invalid_browser_port_fails_closed(monkeypatch, tmp_path, port):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("MODAGENT_CHROME_CDP_PORT", port)
    with pytest.raises(ValueError):
        config.load()
