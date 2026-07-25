"""External game configs are constrained, merged, backed up and verifiable."""

import tempfile
from pathlib import Path

from modagent import user_config


tmp = Path(tempfile.mkdtemp(prefix="modagent-user-config-"))
documents = tmp / "Documents"
backup_root = tmp / "state"
original_root_for = user_config.root_for
original_config_dir = user_config.CONFIG_DIR
user_config.root_for = lambda location: documents
user_config.CONFIG_DIR = str(backup_root)

try:
    target = documents / "My Games" / "FINAL FANTASY VII REBIRTH" / "Saved" / "Config" / "WindowsNoEditor" / "Engine.ini"
    target.parent.mkdir(parents=True)
    target.write_text("[ConsoleVariables]\nr.Streaming=1\n", encoding="utf-8")

    content = """[/Script/EngineSettings.GameMapsSettings]
GameInstanceClass=/FF7RML/BP_EndGameInstance.BP_EndGameInstance_C

[/FF7RML/ModLoaders/BP_ModLoader.BP_ModLoader_C]
bLoggingEnabled=false
bWriteLogsToFile=false
"""
    result = user_config.write_config(
        "documents",
        "My Games/FINAL FANTASY VII REBIRTH/Saved/Config/WindowsNoEditor/Engine.ini",
        content,
        game_slug="finalfantasy7rebirth",
        mod_id="1061",
    )
    merged = target.read_text(encoding="utf-8")
    assert result["written"] and result["verified"], result
    assert "[ConsoleVariables]\nr.Streaming=1" in merged
    assert "GameInstanceClass=/FF7RML/BP_EndGameInstance.BP_EndGameInstance_C" in merged
    assert Path(result["backup_path"]).read_text(encoding="utf-8") == "[ConsoleVariables]\nr.Streaming=1\n"

    # A repeated write replaces its own section and does not duplicate it.
    changed = content.replace("bLoggingEnabled=false", "bLoggingEnabled=true")
    user_config.write_config(
        "documents",
        "My Games/FINAL FANTASY VII REBIRTH/Saved/Config/WindowsNoEditor/Engine.ini",
        changed,
        game_slug="finalfantasy7rebirth",
        mod_id="1061",
    )
    merged = target.read_text(encoding="utf-8")
    assert merged.count("[/FF7RML/ModLoaders/BP_ModLoader.BP_ModLoader_C]") == 1
    assert "bLoggingEnabled=true" in merged
    assert "[ConsoleVariables]\nr.Streaming=1" in merged

    # A custom import ID still owns the numeric Nexus config record. Disabling
    # must neutralize the forced loader sections while preserving user config;
    # enabling must restore the exact managed sections.
    preview = user_config.preview_toggle_mod_configs(
        "finalfantasy7rebirth", ["custom_1061_Reunion_Mod_Loader_v1.2.0"],
    )
    assert preview and preview[0]["exists"], preview
    disabled = user_config.toggle_mod_configs(
        "finalfantasy7rebirth", ["custom_1061_Reunion_Mod_Loader_v1.2.0"], enabling=False,
    )
    assert disabled["complete"] and disabled["changed"], disabled
    neutral = target.read_text(encoding="utf-8")
    assert "GameInstanceClass=" not in neutral
    assert "[ConsoleVariables]\nr.Streaming=1" in neutral
    enabled = user_config.toggle_mod_configs(
        "finalfantasy7rebirth", ["custom_1061_Reunion_Mod_Loader_v1.2.0"], enabling=True,
    )
    assert enabled["complete"] and enabled["changed"], enabled
    assert "GameInstanceClass=" in target.read_text(encoding="utf-8")

    cleanup = user_config.uninstall_mod_configs("finalfantasy7rebirth", "1061")
    assert cleanup["complete"] and cleanup["changed"], cleanup
    restored = target.read_text(encoding="utf-8")
    assert restored == "[ConsoleVariables]\nr.Streaming=1\n", restored

    for invalid in ("../Engine.ini", "C:/Temp/Engine.ini", "/Temp/Engine.ini", "payload.exe"):
        try:
            user_config.resolve_target("documents", invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {invalid}")
finally:
    user_config.root_for = original_root_for
    user_config.CONFIG_DIR = original_config_dir

print("USER CONFIG WRITE TESTS PASSED")
