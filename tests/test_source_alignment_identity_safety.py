import json
import types

from modagent import db, source_alignment, tools
from modagent.sources import thunderstore


def _package(owner, name, version="1.0.0"):
    return {
        "name": name,
        "owner": owner,
        "full_name": f"{owner}-{name}",
        "package_url": f"https://thunderstore.io/c/repo/p/{owner}/{name}/",
        "versions": [{
            "version_number": version,
            "description": name,
            "downloads": 10,
        }],
    }


def _cfg(tmp_path):
    return types.SimpleNamespace(
        game_name="R.E.P.O.",
        game_slug="repo",
        game_id=0,
        game_root=str(tmp_path),
        nexus_api_key="",
        tavily_api_key="",
        tier="subscription",
        chrome_cdp_port=18888,
    )


def _add(mod_id, name):
    db.add_mod(db.InstalledMod(
        id=mod_id,
        name=name,
        version="unknown",
        snapshot_id="",
        files_installed="[]",
        installed_by="imported",
        game_slug="repo",
    ))


def _prepare(monkeypatch, tmp_path, packages):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    monkeypatch.setattr(thunderstore, "community_hint", lambda *_args: "repo")
    monkeypatch.setattr(thunderstore, "find_community", lambda *_args: "repo")
    monkeypatch.setattr(
        thunderstore,
        "list_packages",
        lambda *_args, **_kwargs: packages,
    )


def test_strict_containment_is_not_automatic_identity():
    package = source_alignment._package_row(
        _package("Tansinator", "MapValueTracker")
    )
    assert source_alignment._score({"mapvaluetrackerplus"}, package) < .90
    package = source_alignment._package_row(_package("YMC_MHZ", "MoreHead"))
    assert source_alignment._score({"moreheadbridge"}, package) < .90


def test_same_title_from_multiple_authors_is_ambiguous(
    monkeypatch, tmp_path,
):
    packages = [
        _package("AuthorOne", "UtilityMod"),
        _package("AuthorTwo", "UtilityMod"),
    ]
    _prepare(monkeypatch, tmp_path, packages)
    _add("local_utility", "UtilityMod")

    report = source_alignment.align_installed_mods(_cfg(tmp_path))

    assert not report["bound"]
    assert report["ambiguous"][0]["mod_id"] == "local_utility"
    assert len(report["ambiguous"][0]["candidates"]) == 2
    assert db.get_mod_source_binding("local_utility", "repo") is None


def test_legacy_variant_mismatch_is_removed_and_reaudited(
    monkeypatch, tmp_path,
):
    packages = [_package("YMC_MHZ", "MoreHead")]
    _prepare(monkeypatch, tmp_path, packages)
    _add("local_bridge", "MoreHeadBridge")
    db.upsert_mod_source_binding(
        "repo",
        "local_bridge",
        "thunderstore",
        "YMC_MHZ-MoreHead",
        "https://thunderstore.io/c/repo/p/YMC_MHZ/MoreHead/",
        .97,
        "strong_name",
        "1.0.0",
        {"owner": "YMC_MHZ", "package_name": "MoreHead"},
    )

    report = source_alignment.align_installed_mods(_cfg(tmp_path))

    assert report["summary"]["rejected_bindings"] == 1
    assert report["rejected_bindings"][0]["mod_id"] == "local_bridge"
    assert report["ambiguous"][0]["mod_id"] == "local_bridge"
    assert db.get_mod_source_binding("local_bridge", "repo") is None


def test_direct_update_refuses_unsafe_legacy_binding(
    monkeypatch, tmp_path,
):
    _prepare(monkeypatch, tmp_path, [_package("YMC_MHZ", "MoreHead")])
    _add("local_bridge", "MoreHeadBridge")
    db.upsert_mod_source_binding(
        "repo",
        "local_bridge",
        "thunderstore",
        "YMC_MHZ-MoreHead",
        "https://thunderstore.io/c/repo/p/YMC_MHZ/MoreHead/",
        .97,
        "strong_name",
        "1.0.0",
        {"owner": "YMC_MHZ", "package_name": "MoreHead"},
    )

    result = json.loads(tools.execute(
        "mod_update", {"mod_id": "local_bridge"}, _cfg(tmp_path),
    ))

    assert result["requires_source_alignment"] is True
    assert "已阻止更新" in result["error"]
    assert db.get_mod_source_binding("local_bridge", "repo") is None
