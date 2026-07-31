import json
import os

from modagent import api, db, scanner, snapshot, tools
from modagent.agent import (
    explicit_install_target,
    is_broad_recommendation_request,
    normalize_contextual_install_target,
)
from modagent.config import Config, Tier
from modagent.sources import github


def _touch(path, payload=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def test_download_package_is_one_management_unit(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    game = tmp_path / "StellarBlade"
    package_files = []
    for variant in ("Black", "White"):
        for extension in (".pak", ".ucas", ".utoc"):
            path = game / "SB" / "Content" / "Paks" / "~mods" / (
                f"YoRHa_Outfit_{variant}{extension}"
            )
            _touch(str(path))
            package_files.append(str(path))

    db.add_mod(db.InstalledMod(
        id="550",
        name="YoRHa Unofficial Ceremonial Attire - Modular",
        version="1.0",
        snapshot_id="snap",
        files_installed=json.dumps(package_files),
        installed_by="modagent",
        game_slug="stellarblade",
    ))
    db.add_mod(db.InstalledMod(
        id="local_black_variant",
        name="YoRHa Outfit Black",
        version="unknown",
        snapshot_id="",
        files_installed=json.dumps(package_files[:3]),
        installed_by="imported",
        game_slug="stellarblade",
    ))

    merged = db.merge_duplicate_inventory_rows("stellarblade")
    assert [item["reason"] for item in merged] == ["package_file_subset"]
    saved = db.get_installed_mods("stellarblade")
    assert [(item.id, item.name) for item in saved] == [
        ("550", "YoRHa Unofficial Ceremonial Attire - Modular"),
    ]
    assert all(os.path.isfile(path) for path in package_files)

    # A later disk scan must not recreate either variant as a standalone Mod.
    scan = scanner.scan_existing_mods(
        str(game), "stellarblade", "", game_instance_id="stellarblade",
    )
    assert scan["identified"] == []
    assert scanner.import_mods([{
        "name": "YoRHa Outfit White",
        "version": "unknown",
        "files": package_files[3:],
        "game_slug": "stellarblade",
    }]) == 0

    rows = api.list_mods("stellarblade")
    assert len(rows) == 1
    assert rows[0]["management_unit"] == "package"
    assert rows[0]["file_count"] == 6
    assert rows[0]["variant_count"] == 2


def test_package_subset_merge_stays_conservative_when_owner_is_ambiguous(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    shared = str(tmp_path / "shared.dll")
    first_only = str(tmp_path / "first.dll")
    second_only = str(tmp_path / "second.dll")
    for path in (shared, first_only, second_only):
        _touch(path)
    for mod_id, files in (
        ("one", [shared, first_only]),
        ("two", [shared, second_only]),
    ):
        db.add_mod(db.InstalledMod(
            id=mod_id,
            name=mod_id,
            version="1",
            snapshot_id="",
            files_installed=json.dumps(files),
            installed_by="modagent",
            game_slug="game",
        ))
    db.add_mod(db.InstalledMod(
        id="imported",
        name="ambiguous",
        version="unknown",
        snapshot_id="",
        files_installed=json.dumps([shared]),
        installed_by="imported",
        game_slug="game",
    ))
    assert db.merge_duplicate_inventory_rows("game") == []
    assert len(db.get_installed_mods("game")) == 3


def test_snapshot_guard_uses_install_instance_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    db.add_snapshot(db.Snapshot(
        id="snap_same",
        timestamp=1,
        files="[]",
        trigger_mod_name="test",
        game_slug="gi_same",
    ))
    cfg = Config(
        game_name="R.E.P.O.",
        game_slug="repo",
        game_instance_id="gi_same",
        game_root=str(tmp_path / "REPO"),
        tier=Tier.PRO,
    )
    preview = json.loads(tools.execute(
        "snapshot_delete", {"snapshot_id": "snap_same"}, cfg,
    ))
    assert preview["requires_confirmation"] is True
    assert preview["game_slug"] == "gi_same"

    cfg.game_instance_id = "gi_other"
    rejected = json.loads(tools.execute(
        "snapshot_delete", {"snapshot_id": "snap_same"}, cfg,
    ))
    assert "error" in rejected
    assert rejected.get("requires_confirmation") is not True


def test_snapshot_locator_recovers_historical_bucket_without_false_invalid(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    monkeypatch.setattr(snapshot, "SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    db.init_db()
    db.add_snapshot(db.Snapshot(
        id="snap_historical",
        timestamp=1,
        files="[]",
        trigger_mod_name="legacy",
        game_slug="gi_current",
    ))
    historical = tmp_path / "snapshots" / "repo" / "snap_historical"
    historical.mkdir(parents=True)
    (historical / "manifest.json").write_text(json.dumps({
        "snapshot_id": "snap_historical",
        "files": [],
    }), encoding="utf-8")

    assert snapshot.find_snapshot_dir("snap_historical", "gi_current") == str(historical)
    assert api.list_snapshots("gi_current")[0]["valid"] is True
    assert api.snapshots_reconcile("gi_current")["invalid"] == []


def test_github_requires_game_and_mod_evidence(monkeypatch):
    queries = []

    def fake_json(url):
        queries.append(url)
        return {"items": [
            {
                "name": ".config",
                "full_name": "someone/config",
                "html_url": "https://github.com/someone/config",
                "description": "Super Bunny Man launch log",
                "topics": [],
                "stargazers_count": 10,
                "pushed_at": "2026-07-01T00:00:00Z",
                "archived": False,
            },
            {
                "name": "SuperBunnyMan-Camera-Mod",
                "full_name": "author/SuperBunnyMan-Camera-Mod",
                "html_url": "https://github.com/author/SuperBunnyMan-Camera-Mod",
                "description": "A BepInEx plugin mod for Super Bunny Man",
                "topics": ["super-bunny-man", "bepinex", "mod"],
                "stargazers_count": 20,
                "pushed_at": "2026-07-02T00:00:00Z",
                "archived": False,
            },
        ]}

    monkeypatch.setattr(github, "_http_json", fake_json)
    rows = github.search("camera", "Super Bunny Man")
    assert [row["name"] for row in rows] == ["SuperBunnyMan-Camera-Mod"]
    assert rows[0]["game_evidence"]
    assert rows[0]["mod_evidence"]
    assert "in%3Aname%2Cdescription%2Ctopics" in queries[0]


def test_broad_discovery_and_contextual_entity_normalization():
    assert is_broad_recommendation_request("帮我找找有没有扩展 Mod")
    assert is_broad_recommendation_request("还有没有最色、最热门的我没装的？")
    assert not is_broad_recommendation_request("去 GitHub 搜 BepInEx")
    for misspelling in ("benplex", "beniplex", "bepin ex"):
        parsed = explicit_install_target(f"你先装 {misspelling} 吧")
        normalized, original = normalize_contextual_install_target(
            parsed, "建议先安装 BepInEx 5.x",
        )
        assert normalized["name"] == "BepInEx"
        assert original == misspelling
