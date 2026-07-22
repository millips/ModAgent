import os

from modagent import config


def test_edition_wallpaper_directories_are_isolated(monkeypatch):
    monkeypatch.setenv("MODAGENT_EDITION", "subscription")
    subscription_bg = config.edition_data_dir("bg")

    monkeypatch.setenv("MODAGENT_EDITION", "free")
    free_bg = config.edition_data_dir("bg")

    assert subscription_bg == os.path.join(
        config.CONFIG_DIR, "editions", "subscription", "bg"
    )
    assert free_bg == os.path.join(config.CONFIG_DIR, "editions", "free", "bg")
    assert subscription_bg != free_bg


def test_unknown_edition_falls_back_to_free(monkeypatch):
    monkeypatch.setenv("MODAGENT_EDITION", "unexpected")

    assert config.current_edition() == "free"
