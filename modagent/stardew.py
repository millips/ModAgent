"""Stardew Valley / SMAPI-specific verification and dependency preflight.

The important distinction is:
    files copied != platform configured != SMAPI launched != mods loaded.

This module is read-only.  It never edits Steam's configuration or launches an
executable; it returns copy-ready instructions and evidence that the agent can
report without guessing.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


STEAM_APP_ID = "413150"
SMAPI_EXE = "StardewModdingAPI.exe"
KNOWN_DEPENDENCIES = {
    "pathoschild.contentpatcher": "Content Patcher",
    "esca.farmtypemanager": "Farm Type Manager",
    "spacechase0.genericmodconfigmenu": "Generic Mod Config Menu",
    "spacechase0.jsonassets": "Json Assets",
    "spacechase0.spacecore": "SpaceCore",
    "aedenthorn.extratilesheets": "Extra Map Layers",
    "daisyniko.tilesheets": "DaisyNiko's Tilesheets",
    "flashshifter.stardewvalleyexpandedcp": "Stardew Valley Expanded",
    "pathoschild.smapi": "SMAPI",
}


def is_stardew(game_name: str = "", game_slug: str = "", game_root: str = "") -> bool:
    values = " ".join((game_name, game_slug, os.path.basename(game_root or ""))).casefold()
    compact = re.sub(r"[^a-z0-9]+", "", values)
    return "stardewvalley" in compact


def steam_launch_option(game_root: str) -> str:
    exe = os.path.abspath(os.path.join(game_root, SMAPI_EXE))
    return f'"{exe}" %command%'


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _manifest_id(value: dict) -> str:
    return str(value.get("UniqueID") or value.get("UniqueId") or "").strip()


def installed_manifests(game_root: str) -> list[dict]:
    mods_root = os.path.join(game_root, "Mods")
    if not os.path.isdir(mods_root):
        return []
    result = []
    for current, dirs, files in os.walk(mods_root):
        # Stardew mods are shallow in practice.  Bounding traversal prevents a
        # malformed package from turning a status check into a whole-disk walk.
        depth = len(Path(current).relative_to(mods_root).parts)
        if depth >= 5:
            dirs[:] = []
        manifest_name = next((name for name in files if name.casefold() == "manifest.json"), "")
        if not manifest_name:
            continue
        data = _read_json(os.path.join(current, manifest_name))
        unique_id = _manifest_id(data)
        if not unique_id:
            continue
        result.append({
            "name": str(data.get("Name") or unique_id),
            "unique_id": unique_id,
            "version": str(data.get("Version") or ""),
            "relative_dir": os.path.relpath(current, game_root).replace("\\", "/"),
        })
    return result


def _steam_roots(game_root: str) -> list[str]:
    candidates = []
    override = os.environ.get("MODAGENT_STEAM_DIR", "")
    if override:
        candidates.append(override)

    norm = os.path.abspath(game_root or "")
    match = re.search(r"(?i)^(.*?)[\\/]steamapps[\\/]common(?:[\\/]|$)", norm)
    if match:
        candidates.append(match.group(1))

    if os.name == "nt":
        try:
            import winreg
            for hive, key, name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        candidates.append(str(winreg.QueryValueEx(handle, name)[0]))
                except OSError:
                    continue
        except (ImportError, OSError):
            pass
        for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(os.path.join(base, "Steam"))

    result = []
    seen = set()
    for candidate in candidates:
        path = os.path.realpath(os.path.expandvars(os.path.expanduser(candidate)))
        key = os.path.normcase(path)
        if path and key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _extract_vdf_block(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*\{{', text, re.I)
    if not match:
        return ""
    start = text.find("{", match.start())
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and quoted:
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return ""


def _normalise_launch_option(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("/", "\\").strip()).casefold()


def _vdf_string_value(block: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*"', block, re.I)
    if not match:
        return None
    result = []
    index = match.end()
    while index < len(block):
        char = block[index]
        if char == '"':
            return "".join(result)
        if char == "\\" and index + 1 < len(block):
            following = block[index + 1]
            if following in {'"', "\\"}:
                result.append(following)
                index += 2
                continue
        result.append(char)
        index += 1
    return None


def steam_launch_status(game_root: str) -> dict:
    expected = steam_launch_option(game_root)
    options = []
    profiles_checked = 0
    app_entries = 0
    for steam_root in _steam_roots(game_root):
        userdata = os.path.join(steam_root, "userdata")
        if not os.path.isdir(userdata):
            continue
        try:
            profile_names = os.listdir(userdata)
        except OSError:
            continue
        for profile in profile_names:
            config = os.path.join(userdata, profile, "config", "localconfig.vdf")
            if not os.path.isfile(config):
                continue
            profiles_checked += 1
            try:
                with open(config, "r", encoding="utf-8-sig", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            app_block = _extract_vdf_block(text, STEAM_APP_ID)
            if not app_block:
                continue
            app_entries += 1
            value = _vdf_string_value(app_block, "LaunchOptions")
            if value is not None:
                options.append(value)

    expected_norm = _normalise_launch_option(expected)
    configured = any(_normalise_launch_option(value) == expected_norm for value in options)
    if profiles_checked == 0 or app_entries == 0:
        configured_value = None
    else:
        configured_value = configured
    return {
        "expected": expected,
        "configured": configured_value,
        "profiles_checked": profiles_checked,
        "app_entries_found": app_entries,
        "current_options": options[:5],
    }


def _smapi_version(game_root: str, manifests: list[dict]) -> str:
    for item in manifests:
        if item["unique_id"].casefold() in {"smapi.consolecommands", "smapi.savebackup"}:
            if item["version"]:
                return item["version"]
    return ""


def _smapi_log_path() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(appdata, "StardewValley", "ErrorLogs", "SMAPI-latest.txt")


def _parse_log(path: str, manifests: list[dict]) -> dict:
    if not os.path.isfile(path):
        return {
            "exists": False,
            "path": path,
            "smapi_launched": False,
            "loaded_mods": [],
            "errors_detected": 0,
        }
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()[-512_000:]
        stat = os.stat(path)
    except OSError as exc:
        return {"exists": True, "path": path, "read_error": str(exc), "smapi_launched": False}

    version_match = re.search(r"\bSMAPI\s+(\d+(?:\.\d+){1,3}(?:[-+.\w]*)?)", text, re.I)
    loaded_section = []
    collecting = False
    for line in text.splitlines():
        if re.search(r"\bLoaded\s+\d+\s+mods?\s*:", line, re.I):
            collecting = True
            continue
        if not collecting:
            continue
        body = re.sub(r"^\[[^\]]+\]", "", line)
        entry = re.match(
            r"^\s{2,}(.+?)\s+\d+(?:\.\d+){1,3}(?:[-+.\w]*)?\s+by\s+",
            body,
            re.I,
        )
        if entry:
            loaded_section.append(entry.group(1).strip())
            continue
        # Once entries started, the first non-entry line ends the section.
        if loaded_section and body.strip():
            break

    loaded = []
    for item in manifests:
        if any(item["name"].casefold() == name.casefold() for name in loaded_section):
            loaded.append(item)
    return {
        "exists": True,
        "path": path,
        "mtime": stat.st_mtime,
        "last_run_at": __import__("time").strftime(
            "%Y-%m-%d %H:%M:%S", __import__("time").localtime(stat.st_mtime)
        ),
        "smapi_launched": bool(version_match or "[SMAPI]" in text),
        "smapi_version": version_match.group(1) if version_match else "",
        "loaded_mods": loaded,
        "errors_detected": len(re.findall(r"(?im)^\s*(?:\[[^\]]+\]\s*)?ERROR\b", text)),
        "tail": text[-6000:],
    }


def smapi_status(game_root: str, game_name: str = "", game_slug: str = "") -> dict:
    if not is_stardew(game_name, game_slug, game_root):
        return {"applicable": False, "error": "当前游戏不是星露谷物语"}
    root = os.path.abspath(game_root or "")
    manifests = installed_manifests(root)
    exe = os.path.join(root, SMAPI_EXE)
    required_files = [
        exe,
        os.path.join(root, "StardewModdingAPI.dll"),
        os.path.join(root, "smapi-internal"),
    ]
    files_installed = all(os.path.exists(path) for path in required_files)
    steam = bool(re.search(r"(?i)[\\/]steamapps[\\/]common[\\/]", root))
    launch = steam_launch_status(root) if steam else {
        "expected": exe,
        "configured": None,
        "profiles_checked": 0,
        "app_entries_found": 0,
        "current_options": [],
    }
    log = _parse_log(_smapi_log_path(), manifests)
    custom_loaded = [
        item for item in log.get("loaded_mods", [])
        if not item["unique_id"].casefold().startswith("smapi.")
    ]
    platform_ready = launch["configured"] is True if steam else files_installed
    smapi_ready = files_installed and platform_ready and bool(log.get("smapi_launched"))
    mods_loaded = bool(custom_loaded)

    if not files_installed:
        stage = "smapi_not_installed"
        next_action = "先安装 SMAPI；当前仅检查到部分或没有 SMAPI 文件。"
    elif steam and launch["configured"] is not True:
        stage = "launch_option_pending"
        next_action = f"在 Steam 启动选项中完整粘贴：{launch['expected']}"
    elif not log.get("smapi_launched"):
        stage = "first_launch_pending"
        next_action = "从游戏平台启动一次游戏；出现 SMAPI 黑色控制台后再检查。"
    elif not mods_loaded:
        stage = "mod_load_unverified"
        next_action = "SMAPI 已运行，但尚未从日志确认自定义 Mod 被加载；请检查控制台错误。"
    elif log.get("errors_detected"):
        stage = "loaded_with_errors"
        next_action = "Mod 已加载，但日志含错误；应先处理错误再宣布全部完成。"
    else:
        stage = "complete"
        next_action = "大功告成：SMAPI 已通过平台启动，且日志确认自定义 Mod 已加载。"

    return {
        "applicable": True,
        "game_root": root,
        "platform": "steam" if steam else "other",
        "stage": stage,
        "complete": stage == "complete",
        "smapi_files_installed": files_installed,
        "smapi_executable": exe,
        "smapi_version_from_files": _smapi_version(root, manifests),
        "launch": launch,
        "log": log,
        "installed_mods": manifests,
        "custom_mods_loaded": custom_loaded,
        "next_action": next_action,
        "success_evidence": [
            "启动游戏时同时出现 SMAPI 黑色控制台",
            "控制台或 SMAPI-latest.txt 显示 SMAPI 版本",
            "日志的已加载列表包含目标 Mod，且没有阻断性错误",
        ],
    }


def _dependency_label(unique_id: str) -> str:
    return KNOWN_DEPENDENCIES.get(unique_id.casefold(), unique_id)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or ""))[:4])


def archive_dependency_preflight(
    archive_path: str,
    game_root: str,
    game_name: str = "",
    game_slug: str = "",
) -> dict:
    """Inspect Stardew manifest dependencies before any files are changed."""
    if not is_stardew(game_name, game_slug, game_root):
        return {"applicable": False, "ok": True}

    from . import installer

    package_manifests = []
    with tempfile.TemporaryDirectory(prefix="modagent-stardew-preflight-") as temp:
        installer.extract_archive(archive_path, temp)
        for current, dirs, files in os.walk(temp):
            depth = len(Path(current).relative_to(temp).parts)
            if depth >= 7:
                dirs[:] = []
            manifest_name = next((name for name in files if name.casefold() == "manifest.json"), "")
            if not manifest_name:
                continue
            data = _read_json(os.path.join(current, manifest_name))
            if _manifest_id(data):
                package_manifests.append(data)

    installed = installed_manifests(game_root)
    available_ids = {item["unique_id"].casefold() for item in installed}
    available_versions = {
        item["unique_id"].casefold(): item["version"] for item in installed
    }
    bundled_ids = {_manifest_id(item).casefold() for item in package_manifests}
    bundled_versions = {
        _manifest_id(item).casefold(): str(item.get("Version") or "")
        for item in package_manifests
    }
    smapi_files = all(os.path.exists(os.path.join(game_root, item)) for item in (
        "StardewModdingAPI.exe", "StardewModdingAPI.dll", "smapi-internal",
    ))
    if smapi_files:
        available_ids.add("pathoschild.smapi")
        available_versions["pathoschild.smapi"] = _smapi_version(game_root, installed)

    required = {}
    for manifest in package_manifests:
        minimum_api = str(manifest.get("MinimumApiVersion") or "").strip()
        if minimum_api:
            required.setdefault("pathoschild.smapi", {
                "unique_id": "Pathoschild.SMAPI",
                "name": "SMAPI",
                "minimum_version": minimum_api,
                "required_by": str(manifest.get("Name") or _manifest_id(manifest)),
            })
        content_for = manifest.get("ContentPackFor")
        if isinstance(content_for, dict):
            dep_id = str(content_for.get("UniqueID") or content_for.get("UniqueId") or "").strip()
            if dep_id:
                required.setdefault(dep_id.casefold(), {
                    "unique_id": dep_id,
                    "name": _dependency_label(dep_id),
                    "minimum_version": str(content_for.get("MinimumVersion") or ""),
                    "required_by": str(manifest.get("Name") or _manifest_id(manifest)),
                })
        for dependency in manifest.get("Dependencies") or []:
            if not isinstance(dependency, dict) or dependency.get("IsRequired") is False:
                continue
            dep_id = str(dependency.get("UniqueID") or dependency.get("UniqueId") or "").strip()
            if not dep_id:
                continue
            required.setdefault(dep_id.casefold(), {
                "unique_id": dep_id,
                "name": _dependency_label(dep_id),
                "minimum_version": str(dependency.get("MinimumVersion") or ""),
                "required_by": str(manifest.get("Name") or _manifest_id(manifest)),
            })

    missing = [
        item for key, item in required.items()
        if key not in available_ids and key not in bundled_ids
    ]
    incompatible = []
    for key, item in required.items():
        if key not in available_ids and key not in bundled_ids:
            continue
        minimum = _version_tuple(item.get("minimum_version", ""))
        if not minimum:
            continue
        current_text = available_versions.get(key) or bundled_versions.get(key) or ""
        current = _version_tuple(current_text)
        width = max(len(current), len(minimum))
        if not current or current + (0,) * (width - len(current)) < minimum + (0,) * (width - len(minimum)):
            incompatible.append({
                **item,
                "installed_version": current_text or "unknown",
                "reason": "版本未知，无法验证最低要求" if not current else "已安装版本低于最低要求",
            })
    packages = [{
        "name": str(item.get("Name") or _manifest_id(item)),
        "unique_id": _manifest_id(item),
        "version": str(item.get("Version") or ""),
    } for item in package_manifests]
    return {
        "applicable": True,
        "ok": not missing,
        "packages": packages,
        "required_dependencies": list(required.values()),
        "missing_dependencies": missing,
        "incompatible_dependencies": incompatible,
        "installed_dependency_ids": sorted(available_ids),
        "install_blocked": bool(missing or incompatible),
        "message": (
            "安装前检查发现必需前置缺失或版本不足，已在写入游戏目录前停止。"
            if missing or incompatible else
            "安装前已核对包内 manifest.json，必需前置均已满足。"
        ),
    }
