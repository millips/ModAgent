"""Focused smoke tests for privacy-safe configuration sharing."""

import json
import os
import tempfile

TMP = tempfile.mkdtemp()

from modagent import db

db.DB_FILE = os.path.join(TMP, "share-state.db")
db.init_db()

from modagent.config import Config
from modagent import share_config, tools, official_shares


def main():
    cfg = Config(
        game_name="Example Game",
        game_slug="example-game",
        game_instance_id="example-install",
        game_root=r"D:\Private\Example Game",
        nexus_api_key="must-not-leak",
        llm_api_key="must-not-leak",
    )
    db.add_mod(db.InstalledMod(
        id="alpha", name="Alpha Mod", version="1.2.3", snapshot_id="",
        dependencies=json.dumps(["beta"]), game_slug="example-install",
    ))
    db.add_mod(db.InstalledMod(
        id="beta", name="Beta Framework", version="2.0", snapshot_id="",
        game_slug="example-install",
    ))
    db.upsert_mod_source_binding(
        "example-install", "alpha", "github", "acme/alpha",
        "https://github.com/acme/alpha/releases", confidence=0.95,
    )

    payload = share_config.build_share_payload(cfg, author_note="A safe test")
    raw = share_config.serialize_share(payload)
    assert "must-not-leak" not in raw
    assert r"D:\Private" not in raw
    assert payload["privacy"]["game_paths_included"] is False
    alpha = next(item for item in payload["mods"] if item["local_id"] == "alpha")
    assert alpha["source"]["key"] == "acme/alpha"
    assert alpha["dependencies"] == ["beta"]

    selected = share_config.build_share_payload(
        cfg,
        selected_mod_ids=["alpha"],
        title="Alpha collection",
        description="A selected, source-aligned creator submission.",
        warning="Back up saves first.",
        author_name="Test creator",
        require_verified_sources=True,
    )
    assert [item["local_id"] for item in selected["mods"]] == ["alpha"]
    assert selected["title"] == "Alpha collection"
    assert selected["submission"]["id"].startswith("ms-")
    try:
        share_config.build_share_payload(
            cfg, selected_mod_ids=["beta"], require_verified_sources=True,
        )
        raise AssertionError("Unaligned selected Mod unexpectedly became a submission")
    except share_config.ShareError:
        pass

    decoded, input_kind = share_config.load_share_input(share_config.make_offline_share_link(payload))
    assert input_kind == "offline_link"
    preview = share_config.inspect_share_import(decoded, cfg)
    assert preview["safe_to_auto_install"] is False
    assert preview["summary"]["already_installed"] == 1
    assert preview["summary"]["needs_source_resolution"] == 1

    tool_export = json.loads(tools.execute("share_export", {}, cfg))
    assert tool_export["schema"] == share_config.SCHEMA
    tool_import = json.loads(tools.execute("share_import", {"share": tool_export["share_json"]}, cfg))
    assert tool_import["kind"] == "share_import_preview"

    official_manifest = dict(payload)
    official_manifest["kind"] = "official_collection"
    official_manifest["share_id"] = "ma-example-game-000001"
    official_manifest["game"] = {"name": "Example Game", "slug": "example-game", "mod_loader": ""}
    index_url = "https://raw.githubusercontent.com/millips/ModAgent/main/shares/index.json"
    manifest_url = "https://raw.githubusercontent.com/millips/ModAgent/main/shares/collections/ma-example-game-000001.json"
    index = {
        "schema": official_shares.INDEX_SCHEMA,
        "collections": [{
            "id": "ma-example-game-000001", "game_slug": "example-game", "game_name": "Example Game",
            "title": "Example collection", "description": "Reviewed test collection",
            "tags": ["test"], "warnings": [], "mod_count": 2,
            "updated_at": "2026-07-31T00:00:00Z", "manifest_url": manifest_url,
        }],
    }
    original_read = share_config._read_remote_share
    try:
        share_config._read_remote_share = lambda url: (
            json.dumps(index) if url == index_url else json.dumps(official_manifest)
            if url == manifest_url else (_ for _ in ()).throw(AssertionError(url))
        )
        cfg.official_share_index_url = index_url
        catalog = official_shares.load_catalog(cfg)
        assert catalog["fetched"] and catalog["collections"][0]["id"] == "ma-example-game-000001"
        official_preview = official_shares.inspect_official_collection(cfg, "MA-EXAMPLE-GAME-000001")
        assert official_preview["kind"] == "official_share_import_preview"
        assert official_preview["summary"]["already_installed"] == 1
        via_tool = json.loads(tools.execute("official_share_import", {"share_id": "ma-example-game-000001"}, cfg))
        assert via_tool["source_kind"] == "official_collection"
    finally:
        share_config._read_remote_share = original_read

    # Base runtimes are root-level framework files, not normal Mod rows.
    # Their real on-disk presence must unblock the official plan preview.
    runtime_root = os.path.join(TMP, "runtime-game")
    os.makedirs(os.path.join(runtime_root, "BepInEx", "core"), exist_ok=True)
    with open(os.path.join(runtime_root, "BepInEx", "core", "BepInEx.Core.dll"), "wb") as stream:
        stream.write(b"runtime")
    runtime_cfg = Config(game_slug="repo", game_instance_id="runtime-game", game_root=runtime_root)
    runtime_payload = {
        "schema": share_config.SCHEMA, "kind": "official_collection",
        "game": {"slug": "repo", "name": "R.E.P.O."}, "mods": [{
            "local_id": "alpha", "name": "Alpha", "source": {"type": "thunderstore", "key": "a-alpha", "url": "https://thunderstore.io/c/repo/p/a/Alpha/"},
            "dependencies": ["BepInEx-BepInExPack-5.4.2305"],
        }],
    }
    runtime_preview = share_config.inspect_share_import(runtime_payload, runtime_cfg)
    runtime_requirement = runtime_preview["summary"]["host_dependency_requirements"][0]
    assert runtime_requirement["status"] == "satisfied_base_environment"
    assert runtime_requirement["evidence"] == ["BepInEx/core/BepInEx.Core.dll"]

    try:
        share_config.load_share_input("https://example.invalid/share.json")
        raise AssertionError("Unexpected non-GitHub remote source accepted")
    except share_config.ShareError:
        pass
    print("SHARE CONFIG TESTS PASSED")


if __name__ == "__main__":
    main()
