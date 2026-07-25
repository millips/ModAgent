"""Constrained writes to per-user game configuration roots.

This is deliberately narrower than arbitrary filesystem access: callers select
a Windows known-folder alias and provide a relative configuration-file path.
Absolute paths, traversal, executables and symlink escapes are rejected.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import tempfile
import time
import uuid
import json
from pathlib import Path

from .config import CONFIG_DIR


_KNOWN_FOLDER_IDS = {
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "saved_games": "4C5C32FF-BB9D-43B0-BF5B-6B871C904A28",
}
_ALLOWED_EXTENSIONS = {".ini", ".cfg", ".json", ".toml", ".xml", ".txt"}
_SECTION_RE = re.compile(r"^\s*\[([^\]\r\n]+)\]\s*$")


def _registry_path() -> Path:
    return Path(CONFIG_DIR) / "external-config-registry.json"


def _load_registry() -> list[dict]:
    path = _registry_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_registry(items: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _entry_key(item: dict) -> tuple[str, str, str]:
    return (str(item.get("game_slug") or ""), str(item.get("location") or ""),
            str(item.get("relative_path") or "").replace("\\", "/"))


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> _GUID:
    parsed = uuid.UUID(value)
    return _GUID(
        parsed.time_low, parsed.time_mid, parsed.time_hi_version,
        (ctypes.c_ubyte * 8)(*parsed.bytes[8:]),
    )


def _known_folder(folder_id: str) -> str:
    if os.name != "nt":
        return ""
    output = ctypes.c_wchar_p()
    guid = _guid(folder_id)
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(output),
    )
    if result != 0:
        return ""
    try:
        return output.value or ""
    finally:
        ctypes.windll.ole32.CoTaskMemFree(output)


def root_for(location: str) -> Path:
    key = str(location or "").strip().lower()
    if key in _KNOWN_FOLDER_IDS:
        value = _known_folder(_KNOWN_FOLDER_IDS[key])
        if value:
            return Path(value)
        fallback = "Documents" if key == "documents" else "Saved Games"
        return Path.home() / fallback
    if key == "local_appdata":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
    if key == "roaming_appdata":
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming"))
    raise ValueError("不支持的用户配置位置")


def resolve_target(location: str, relative_path: str) -> tuple[Path, Path]:
    raw = str(relative_path or "").replace("\\", "/").strip()
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or ":" in raw:
        raise ValueError("配置路径必须是相对路径")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("配置路径不能包含空段、. 或 ..")
    if candidate.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ValueError("只允许写入常见文本配置文件")
    root = root_for(location).resolve()
    target = (root / candidate).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError("配置路径越过允许的用户目录")
    return root, target


def _section_blocks(text: str) -> dict[str, list[str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: dict[str, list[str]] = {}
    current = None
    for line in lines:
        match = _SECTION_RE.match(line)
        if match:
            current = match.group(1).strip().lower()
            blocks[current] = [line.rstrip()]
        elif current is not None:
            blocks[current].append(line.rstrip())
    return blocks


def merge_ini(existing: str, incoming: str) -> str:
    """Replace only incoming INI sections, preserving every unrelated section."""
    incoming_blocks = _section_blocks(incoming)
    if not incoming_blocks:
        raise ValueError("写入内容没有有效的 INI section")
    lines = existing.replace("\r\n", "\n").replace("\r", "\n").split("\n") if existing else []
    output: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        match = _SECTION_RE.match(lines[index])
        if not match:
            output.append(lines[index].rstrip())
            index += 1
            continue
        key = match.group(1).strip().lower()
        end = index + 1
        while end < len(lines) and not _SECTION_RE.match(lines[end]):
            end += 1
        if key in incoming_blocks:
            output.extend(incoming_blocks[key])
            seen.add(key)
        else:
            output.extend(line.rstrip() for line in lines[index:end])
        index = end
    for key, block in incoming_blocks.items():
        if key in seen:
            continue
        if output and output[-1] != "":
            output.append("")
        output.extend(block)
    return "\n".join(output).rstrip() + "\n"


def _rewrite_sections(existing: str, replacements: dict[str, list[str] | None]) -> str:
    """Replace/remove selected sections while preserving preamble and unrelated sections."""
    lines = existing.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output, handled = [], set()
    index = 0
    while index < len(lines):
        match = _SECTION_RE.match(lines[index])
        if not match:
            output.append(lines[index].rstrip())
            index += 1
            continue
        key = match.group(1).strip().lower()
        end = index + 1
        while end < len(lines) and not _SECTION_RE.match(lines[end]):
            end += 1
        if key in replacements:
            block = replacements[key]
            if block:
                output.extend(block)
            handled.add(key)
        else:
            output.extend(line.rstrip() for line in lines[index:end])
        index = end
    for key, block in replacements.items():
        if key not in handled and block:
            if output and output[-1] != "":
                output.append("")
            output.extend(block)
    return "\n".join(output).rstrip() + ("\n" if any(line.strip() for line in output) else "")


def _atomic_write_text(target: Path, value: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def write_config(
    location: str, relative_path: str, content: str, *,
    game_slug: str = "", mod_id: str = "", mode: str = "merge_ini",
) -> dict:
    encoded = str(content or "").encode("utf-8")
    if not encoded or len(encoded) > 256 * 1024:
        raise ValueError("配置内容为空或超过 256KB")
    root, target = resolve_target(location, relative_path)
    existed = target.is_file()
    existing = target.read_text(encoding="utf-8-sig", errors="replace") if existed else ""
    if mode == "merge_ini":
        result_text = merge_ini(existing, content)
    elif mode == "create_or_replace":
        result_text = str(content).replace("\r\n", "\n").replace("\r", "\n")
        if not result_text.endswith("\n"):
            result_text += "\n"
    else:
        raise ValueError("不支持的配置写入模式")

    backup_path = ""
    if existed:
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
        backup = (
            Path(CONFIG_DIR) / "external-config-backups"
            / (game_slug or "_unknown") / (mod_id or "_unbound") / stamp
            / str(location).lower() / Path(str(relative_path).replace("\\", "/"))
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        backup_path = str(backup)

    _atomic_write_text(target, result_text)

    verified = target.read_text(encoding="utf-8-sig", errors="replace") == result_text
    if verified and game_slug:
        items = _load_registry()
        key = (str(game_slug), str(location).lower(), str(relative_path).replace("\\", "/"))
        entry = next((item for item in items if _entry_key(item) == key), None)
        if entry is None:
            entry = {
                "game_slug": key[0], "location": key[1], "relative_path": key[2],
                "first_seen_at": time.time(), "original_existed": existed,
                "original_backup": backup_path if existed else "",
            }
            items.append(entry)
        entry["latest_hash"] = hashlib.sha256(target.read_bytes()).hexdigest()
        entry["mod_id"] = str(mod_id or entry.get("mod_id") or "")
        if mod_id:
            owners = entry.setdefault("owners", {})
            owner = owners.setdefault(str(mod_id), {"mode": mode, "sections": [], "previous_sections": {}})
            if mode == "merge_ini":
                before = _section_blocks(existing)
                for section in _section_blocks(content):
                    if section not in owner["sections"]:
                        owner["sections"].append(section)
                        owner["previous_sections"][section] = before.get(section)
            elif "previous_backup" not in owner:
                owner["previous_backup"] = backup_path if existed else ""
                owner["previous_existed"] = existed
        _save_registry(items)
    return {
        "written": verified,
        "verified": verified,
        "location": str(location).lower(),
        "root": str(root),
        "relative_path": str(relative_path).replace("\\", "/"),
        "path": str(target),
        "existed_before": existed,
        "backup_path": backup_path,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "mode": mode,
    }


def capture_snapshot(game_slug: str, snap_dir: str) -> list[dict]:
    """Copy every managed external config for this game into a snapshot."""
    result = []
    for item in _load_registry():
        if item.get("game_slug") != game_slug:
            continue
        _, target = resolve_target(item["location"], item["relative_path"])
        record = {"location": item["location"], "relative_path": item["relative_path"],
                  "existed": target.is_file()}
        if target.is_file():
            digest = hashlib.sha256((item["location"] + "\0" + item["relative_path"]).encode()).hexdigest()
            rel = f"_external_configs/{digest}{target.suffix.lower()}"
            stored = Path(snap_dir) / Path(rel)
            stored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, stored)
            record.update({"stored_path": rel, "sha256": hashlib.sha256(stored.read_bytes()).hexdigest()})
        result.append(record)
    return result


def preview_snapshot(snap_dir: str, manifest: dict) -> dict:
    """Plan external-config restore without changing the user's files."""
    slug = str(manifest.get("game_slug") or "")
    timestamp = float(manifest.get("timestamp") or 0)
    captured = {_entry_key({"game_slug": slug, **item}): item
                for item in (manifest.get("external_configs") or [])}
    actions, unchanged, failed = [], 0, []
    for item in _load_registry():
        if item.get("game_slug") != slug:
            continue
        key = _entry_key(item)
        desired = captured.get(key)
        source = ""
        desired_exists = False
        if desired is not None:
            desired_exists = bool(desired.get("existed"))
            if desired_exists:
                source = str(Path(snap_dir) / desired.get("stored_path", ""))
        elif float(item.get("first_seen_at") or 0) >= timestamp:
            desired_exists = bool(item.get("original_existed"))
            source = str(item.get("original_backup") or "") if desired_exists else ""
        else:
            continue  # Old snapshot predates registry knowledge; fail closed and leave it alone.
        try:
            _, target = resolve_target(item["location"], item["relative_path"])
            if desired_exists:
                if not source or not os.path.isfile(source):
                    failed.append({"path": str(target), "reason": "snapshot_source_missing"})
                elif target.is_file() and hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(Path(source).read_bytes()).digest():
                    unchanged += 1
                else:
                    actions.append({"action": "restore", "path": str(target), "source": source,
                                    "location": item["location"], "relative_path": item["relative_path"]})
            elif target.exists():
                actions.append({"action": "delete", "path": str(target),
                                "location": item["location"], "relative_path": item["relative_path"]})
            else:
                unchanged += 1
        except Exception as exc:
            failed.append({"path": item.get("relative_path", ""), "reason": str(exc)})
    return {"actions": actions, "action_count": len(actions), "unchanged": unchanged, "failed": failed}


def restore_snapshot(snap_dir: str, manifest: dict) -> dict:
    plan = preview_snapshot(snap_dir, manifest)
    restored = deleted = 0
    failed = list(plan["failed"])
    for action in plan["actions"]:
        target = Path(action["path"])
        try:
            if action["action"] == "delete":
                target.unlink(missing_ok=True)
                deleted += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
                os.close(fd)
                try:
                    shutil.copy2(action["source"], temp_name)
                    os.replace(temp_name, target)
                finally:
                    if os.path.exists(temp_name):
                        os.remove(temp_name)
                restored += 1
        except Exception as exc:
            failed.append({"path": str(target), "reason": str(exc), "action": action["action"]})
    after = preview_snapshot(snap_dir, manifest)
    all_failed = failed + after["failed"]
    complete = not after["actions"] and not all_failed
    return {"complete": complete, "restored": restored, "deleted": deleted,
            "unchanged_verified": after["unchanged"], "pending": after["actions"], "failed": all_failed}


def uninstall_mod_configs(game_slug: str, mod_id: str) -> dict:
    """Undo only the external config portions owned by one Mod."""
    items = _load_registry()
    changed, skipped, failed = [], [], []
    for entry in items:
        if entry.get("game_slug") != game_slug:
            continue
        owners = entry.get("owners") or {}
        owner = owners.get(str(mod_id))
        if not owner:
            continue
        try:
            _, target = resolve_target(entry["location"], entry["relative_path"])
            other_sections = {section for oid, info in owners.items() if oid != str(mod_id)
                              for section in (info.get("sections") or [])}
            if owner.get("mode") == "merge_ini" and target.is_file():
                replacements = {}
                for section in owner.get("sections") or []:
                    if section in other_sections:
                        skipped.append({"path": str(target), "section": section, "reason": "shared_owner"})
                        continue
                    replacements[section] = (owner.get("previous_sections") or {}).get(section)
                if replacements:
                    updated = _rewrite_sections(target.read_text(encoding="utf-8-sig", errors="replace"), replacements)
                    if updated:
                        _atomic_write_text(target, updated)
                    else:
                        target.unlink(missing_ok=True)
                    changed.append({"path": str(target), "sections": sorted(replacements)})
            elif owner.get("mode") == "create_or_replace" and len(owners) == 1:
                backup = owner.get("previous_backup") or ""
                if owner.get("previous_existed") and os.path.isfile(backup):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                elif not owner.get("previous_existed"):
                    target.unlink(missing_ok=True)
                changed.append({"path": str(target), "whole_file": True})
            owners.pop(str(mod_id), None)
            entry["owners"] = owners
            entry["latest_hash"] = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
        except Exception as exc:
            failed.append({"path": entry.get("relative_path", ""), "error": str(exc)})
    _save_registry(items)
    return {"complete": not failed, "changed": changed, "skipped_shared": skipped, "failed": failed}


def _owner_matches(owner_id: str, mod_ids: set[str]) -> bool:
    """Match canonical and custom-import IDs (custom_123_name -> 123)."""
    owner = str(owner_id or "")
    if owner in mod_ids:
        return True
    for mod_id in mod_ids:
        match = re.match(r"^custom_([^_]+)_", str(mod_id))
        if match and owner == match.group(1):
            return True
    return False


def preview_toggle_mod_configs(game_slug: str, mod_ids: list[str]) -> list[dict]:
    ids = {str(value) for value in mod_ids}
    result = []
    for entry in _load_registry():
        if entry.get("game_slug") != game_slug:
            continue
        matched = [oid for oid in (entry.get("owners") or {}) if _owner_matches(oid, ids)]
        if not matched:
            continue
        try:
            _, target = resolve_target(entry["location"], entry["relative_path"])
            result.append({
                "path": str(target), "exists": target.is_file(),
                "location": entry["location"], "relative_path": entry["relative_path"],
                "owners": matched,
            })
        except Exception as exc:
            result.append({"relative_path": entry.get("relative_path", ""), "error": str(exc), "owners": matched})
    return result


def toggle_mod_configs(game_slug: str, mod_ids: list[str], *, enabling: bool) -> dict:
    """Reversibly disable/enable external config portions owned by Mods."""
    ids = {str(value) for value in mod_ids}
    items = _load_registry()
    changed, skipped, failed = [], [], []
    for entry in items:
        if entry.get("game_slug") != game_slug:
            continue
        owners = entry.get("owners") or {}
        matched = [(oid, info) for oid, info in owners.items() if _owner_matches(oid, ids)]
        if not matched:
            continue
        try:
            _, target = resolve_target(entry["location"], entry["relative_path"])
            for oid, owner in matched:
                mode = owner.get("mode")
                if enabling:
                    if not owner.get("disabled"):
                        continue
                    if mode == "merge_ini":
                        replacements = owner.get("disabled_sections") or {}
                        existing = target.read_text(encoding="utf-8-sig", errors="replace") if target.is_file() else ""
                        updated = _rewrite_sections(existing, replacements)
                        if updated:
                            _atomic_write_text(target, updated)
                    else:
                        backup = owner.get("disabled_backup") or ""
                        if backup and os.path.isfile(backup):
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(backup, target)
                        else:
                            raise FileNotFoundError("disabled external-config backup missing")
                    owner["disabled"] = False
                    changed.append({"path": str(target), "owner": oid, "enabled": True})
                else:
                    if owner.get("disabled"):
                        continue
                    if mode == "merge_ini" and target.is_file():
                        blocks = _section_blocks(target.read_text(encoding="utf-8-sig", errors="replace"))
                        replacements = {}
                        captured = {}
                        other_sections = {section for other_id, info in owners.items()
                                          if other_id != oid and not info.get("disabled")
                                          for section in (info.get("sections") or [])}
                        for section in owner.get("sections") or []:
                            if section in other_sections:
                                skipped.append({"path": str(target), "section": section, "reason": "shared_owner"})
                                continue
                            captured[section] = blocks.get(section)
                            replacements[section] = (owner.get("previous_sections") or {}).get(section)
                        updated = _rewrite_sections(target.read_text(encoding="utf-8-sig", errors="replace"), replacements)
                        if updated:
                            _atomic_write_text(target, updated)
                        else:
                            target.unlink(missing_ok=True)
                        owner["disabled_sections"] = captured
                    elif mode == "create_or_replace" and target.is_file():
                        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
                        backup = Path(CONFIG_DIR) / "external-config-disabled" / game_slug / oid / stamp / Path(entry["relative_path"])
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup)
                        owner["disabled_backup"] = str(backup)
                        original = owner.get("previous_backup") or ""
                        if owner.get("previous_existed") and os.path.isfile(original):
                            shutil.copy2(original, target)
                        else:
                            target.unlink(missing_ok=True)
                    owner["disabled"] = True
                    changed.append({"path": str(target), "owner": oid, "disabled": True})
            entry["owners"] = owners
            entry["latest_hash"] = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
        except Exception as exc:
            failed.append({"path": entry.get("relative_path", ""), "error": str(exc)})
    _save_registry(items)
    return {"complete": not failed, "changed": changed, "skipped_shared": skipped, "failed": failed}
