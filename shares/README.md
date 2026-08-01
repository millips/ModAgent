# ModAgent official collections

This folder is the zero-server, reviewed catalogue for ModAgent collections.
Every approved collection receives a stable code such as `ma-263484`.

## Review flow

1. Add a reviewed `official_collection` manifest under `shares/collections/`.
2. Add one corresponding entry to `index.json`.
3. Ensure every Mod has a source URL or stable source key, clear warnings, and
   no API keys, local paths, archive files, or private configuration values.
4. Open the raw `index.json` on GitHub and test the code in ModAgent.

The client treats this repository as a catalogue only. Choosing a collection
always produces a preview first; normal source, dependency, conflict, loader,
and duplicate checks still run before any installation.

## Index entry

```json
{
  "id": "ma-263484",
  "game_slug": "example-game",
  "game_name": "Example Game",
  "title": "Starter collection",
  "description": "A reviewed collection description.",
  "tags": ["starter", "quality-of-life"],
  "warnings": ["Back up saves before changing a large collection."],
  "mod_count": 3,
  "updated_at": "2026-07-31T00:00:00Z",
  "manifest_url": "https://raw.githubusercontent.com/millips/ModAgent/main/shares/collections/ma-263484.json"
}
```

`manifest_url` must use `raw.githubusercontent.com`. It is intentionally
restricted so a collection code cannot make the desktop client fetch a local
network address or an arbitrary website.
