"""Installed Mod catalogue gets cached, evidence-labelled Chinese summaries."""
import json
import os
import tempfile
from types import SimpleNamespace

from modagent import db
from modagent.catalog_enrichment import (
    build_enrichment_inputs,
    generate_catalog_notes,
)


tmp = tempfile.mkdtemp(prefix="modagent_catalog_")
db.DB_FILE = os.path.join(tmp, "state.db")
db.init_db()

mod_dir = os.path.join(tmp, "game", "BepInEx", "plugins", "MapTracker")
os.makedirs(mod_dir)
manifest = os.path.join(mod_dir, "manifest.json")
with open(manifest, "w", encoding="utf-8") as handle:
    json.dump({
        "Name": "Map Tracker",
        "Description": "Shows teammates and scanned valuables on the map.",
    }, handle)

mod = db.InstalledMod(
    id="map-tracker",
    name="MapTracker",
    version="1.2.0",
    snapshot_id="",
    files_installed=json.dumps([manifest]),
    game_slug="repo",
)
db.add_mod(mod)

rows = build_enrichment_inputs(
    [mod], bindings={}, cached={}, allowed_roots=[os.path.join(tmp, "game")],
)
assert len(rows) == 1
assert rows[0]["evidence_kind"] == "local_manifest"
assert "scanned valuables" in rows[0]["evidence"]


class FakeCompletions:
    @staticmethod
    def create(**_kwargs):
        message = SimpleNamespace(content=json.dumps({
            "items": [{
                "mod_id": "map-tracker",
                "localized_name": "地图追踪器",
                "summary": "在地图上显示队友和已经扫描出的贵重物品。",
            }]
        }, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


client = SimpleNamespace(
    chat=SimpleNamespace(completions=FakeCompletions())
)
notes = generate_catalog_notes(client, "test-model", rows)
assert notes[0]["localized_name"] == "地图追踪器"
assert notes[0]["confidence"] == "high"
assert notes[0]["evidence_kind"] == "local_manifest"

assert db.upsert_mod_catalog_notes("repo", notes) == 1
cached = db.get_mod_catalog_notes("repo")
assert cached["map-tracker"]["summary"].startswith("在地图上显示")
assert build_enrichment_inputs(
    [mod], bindings={}, cached=cached, allowed_roots=[os.path.join(tmp, "game")],
) == []

unknown = db.InstalledMod(
    id="mystery",
    name="BetterJump",
    version="unknown",
    snapshot_id="",
    files_installed="[]",
    game_slug="repo",
)
unknown_rows = build_enrichment_inputs(
    [unknown], bindings={}, cached={}, allowed_roots=[os.path.join(tmp, "game")],
)
unknown_notes = generate_catalog_notes(
    SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_kwargs: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"items": [{
                "mod_id": "mystery",
                "localized_name": "更好的跳跃",
                "summary": "增强跳跃体验。",
            }]}, ensure_ascii=False))
        )])
    ))),
    "test-model",
    unknown_rows,
)
assert unknown_notes[0]["confidence"] == "low"
assert unknown_notes[0]["summary"].startswith("可能")

db.remove_mod("map-tracker", "repo")
assert "map-tracker" not in db.get_mod_catalog_notes("repo")

print("ALL PASS")
