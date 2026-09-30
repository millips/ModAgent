"""Regression coverage for stable-ID source alignment candidates."""
import types

from modagent import db, nexus, source_alignment
from modagent.sources import thunderstore


def _cfg(tmp_path):
    return types.SimpleNamespace(
        game_name="Stardew Valley", game_slug="stardewvalley", game_id=0,
        game_root=str(tmp_path), nexus_api_key="key", tavily_api_key="key",
        chrome_cdp_port=18888,
    )


def test_nexus_rows_are_deduped_before_manual_review(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    db.add_mod(db.InstalledMod(
        id="local_soft_seasons", name="Soft Slow Seasons", version="1.6.4",
        snapshot_id="", files_installed="[]", installed_by="imported",
        game_slug="stardewvalley",
    ))
    monkeypatch.setattr(thunderstore, "community_hint", lambda *_: None)
    monkeypatch.setattr(thunderstore, "find_community", lambda *_: None)
    # Three search URLs for Nexus #23095 are one project, not three choices.
    monkeypatch.setattr(nexus, "search", lambda *_args, **_kwargs: [
        {"mod_id": 23095, "name": "Soft Slow Seasons", "summary": "[center]overview[/center]"},
        {"mod_id": 23095, "name": "Soft Slow Seasons", "summary": "[center]files[/center]"},
        {"mod_id": 23095, "name": "Soft Slow Seasons", "summary": "[center]images[/center]"},
        {"mod_id": 8912, "name": "Slow Seasons", "summary": "different project"},
    ])
    monkeypatch.setattr(nexus, "get_detail", lambda mod_id, *_args: {
        "name": "Soft Slow Seasons" if mod_id == 23095 else "Slow Seasons",
        "version": "1.6.4", "author": "Author",
        "summary": "[center]clean summary[/center]",
        "description": "[url=https://example.test]clean description[/url]",
        "dependencies": [], "updated_at": "",
    })

    report = source_alignment.align_installed_mods(_cfg(tmp_path))

    # The distinct low-score project can still require confirmation, but the
    # three URL variants of #23095 must never be shown as three choices.
    assert report["summary"]["ambiguous"] == 1, report
    candidates = report["ambiguous"][0]["candidates"]
    assert [item["source_key"] for item in candidates] == ["23095", "8912"]
    assert all("[center]" not in item.get("summary", "") for item in candidates)


def test_plain_text_removes_nexus_markup():
    assert nexus._source_plain_text(
        "[center][url=https://example.test]Soft Slow Seasons[/url][/center]<br>OK"
    ) == "Soft Slow Seasons\nOK"
