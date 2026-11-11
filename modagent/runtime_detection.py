"""Conservative on-disk detection for game Mod runtimes/loaders."""

from __future__ import annotations

import os


def loader_evidence(game_root: str, loader: str) -> dict:
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(str(game_root or ""))))
    wanted = str(loader or "").strip().casefold()
    if not root or not os.path.isdir(root):
        return {"installed": False, "loader": loader, "evidence": []}

    if wanted in {"bepinex", "bepinexpack"}:
        core = os.path.join(root, "BepInEx", "core")
        direct = [
            os.path.join(core, "BepInEx.dll"),
            os.path.join(core, "BepInEx.Core.dll"),
        ]
        hits = [path for path in direct if os.path.isfile(path)]
        if os.path.isdir(core):
            hits.extend(
                os.path.join(core, name)
                for name in os.listdir(core)
                if name.casefold().startswith("bepinex") and name.casefold().endswith(".dll")
            )
        bootstrap = [
            os.path.join(root, name)
            for name in ("winhttp.dll", "doorstop_config.ini")
            if os.path.isfile(os.path.join(root, name))
        ]
        log = os.path.join(root, "BepInEx", "LogOutput.log")
        if os.path.isfile(log):
            hits.append(log)
        hits = list(dict.fromkeys(hits + bootstrap))
        # A BepInEx-named core DLL is authoritative. A populated BepInEx tree
        # plus both Doorstop bootstrap files is also a valid installation even
        # when a distribution renamed the assembly.
        installed = any(
            os.path.basename(path).casefold().startswith("bepinex")
            and path.casefold().endswith(".dll")
            for path in hits
        ) or (os.path.isdir(core) and len(bootstrap) == 2)
    elif wanted in {"melonloader", "melon"}:
        hits = [
            os.path.join(root, name)
            for name in ("MelonLoader", "version.dll")
            if os.path.exists(os.path.join(root, name))
        ]
        installed = os.path.isdir(os.path.join(root, "MelonLoader")) and bool(hits)
    elif wanted == "smapi":
        hits = [
            os.path.join(root, name)
            for name in ("StardewModdingAPI.exe", "StardewModdingAPI.dll")
            if os.path.isfile(os.path.join(root, name))
        ]
        installed = bool(hits)
    else:
        hits, installed = [], False

    return {
        "installed": installed,
        "loader": loader,
        "evidence": [os.path.relpath(path, root).replace("\\", "/") for path in hits],
    }


def active_loaders(game_root: str) -> list[str]:
    return [
        loader for loader in ("BepInEx", "MelonLoader", "SMAPI")
        if loader_evidence(game_root, loader)["installed"]
    ]
