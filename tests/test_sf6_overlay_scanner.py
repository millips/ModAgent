"""Regression: RE Engine overlay files must not become one fake Mod each."""

import json
import os
import tempfile
from types import SimpleNamespace

from modagent.scanner import _scan_streetfighter6_overlays


with tempfile.TemporaryDirectory() as root:
    folder = os.path.join(root, "natives", "stm", "product", "model", "esf", "esf028", "001", "01")
    os.makedirs(folder)
    owned = os.path.join(folder, "owned.mesh.230110883")
    unknown = os.path.join(folder, "unknown.tex.241101895")
    open(owned, "wb").close()
    open(unknown, "wb").close()
    result = _scan_streetfighter6_overlays(
        root, [SimpleNamespace(files_installed=json.dumps([owned]))]
    )
    assert result["detected"] == 2
    assert result["owned_packages"] == 1
    assert sum(item["file_count"] for item in result["unidentified"]) == 1

print("SF6 OVERLAY SCANNER TEST PASSED")
