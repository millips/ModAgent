import os
import tempfile

from modagent.runtime_detection import active_loaders, loader_evidence


with tempfile.TemporaryDirectory(prefix="modagent-runtime-detect-") as game:
    os.makedirs(os.path.join(game, "BepInEx", "core"))
    # An empty shell folder is not proof of a valid runtime.
    assert not loader_evidence(game, "BepInEx")["installed"]
    with open(os.path.join(game, "BepInEx", "core", "BepInEx.Core.dll"), "wb") as stream:
        stream.write(b"runtime")
    result = loader_evidence(game, "BepInEx")
    assert result["installed"]
    assert "BepInEx/core/BepInEx.Core.dll" in result["evidence"]
    assert active_loaders(game) == ["BepInEx"]

print("RUNTIME DETECTION TEST PASSED")
