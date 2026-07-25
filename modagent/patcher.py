import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional, Any


def patch_file(file_path: str, instruction: str) -> dict:
    if not os.path.exists(file_path):
        return {"success": False, "error": f"文件不存在: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".json":
            return _patch_json(file_path, instruction)
        elif ext == ".xml":
            return _patch_xml(file_path, instruction)
        elif ext in (".esp", ".esm"):
            return {"success": False, "error":
                    f"{ext} 属于二进制插件格式，未修改文件；请使用专用工具（如 xEdit）"}
        elif ext in (".ini", ".cfg", ".txt"):
            return _patch_text(file_path, instruction)
        else:
            return {"success": False, "error": f"不支持的文件类型: {ext}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _patch_json(file_path: str, instruction: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        original = json.load(f)

    patch_ops = _parse_instruction(instruction)
    if not patch_ops:
        return {"success": False, "error": f"无法解析指令: {instruction}"}

    modified = json.loads(json.dumps(original))

    for op in patch_ops:
        keys = op.get("path", "").split(".")
        value = op.get("value")
        target = modified
        for key in keys[:-1]:
            idx_match = re.match(r"^(\w+)\[(\d+)\]$", key)
            if idx_match:
                target = target[idx_match.group(1)][int(idx_match.group(2))]
            else:
                target = target[key]
        last = keys[-1]
        idx_match = re.match(r"^(\w+)\[(\d+)\]$", last)
        if idx_match:
            target[idx_match.group(1)][int(idx_match.group(2))] = value
        else:
            target[last] = value

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(modified, f, indent=2, ensure_ascii=False)

    return {"success": True, "diff": _generate_diff(json.dumps(original, indent=2), json.dumps(modified, indent=2)),
            "path": file_path}


def _patch_xml(file_path: str, instruction: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        original = f.read()

    patch_ops = _parse_instruction(instruction)
    if not patch_ops:
        return {"success": False, "error": f"无法解析指令: {instruction}"}

    root = ET.fromstring(original)
    changed = []
    for op in patch_ops:
        raw_path = str(op.get("path") or "").strip().strip("/")
        parts = [part for part in re.split(r"[./]", raw_path) if part]
        if parts and parts[0] == root.tag:
            parts.pop(0)
        attribute = ""
        if parts and parts[-1].startswith("@"):
            attribute = parts.pop()[1:]
        elif parts and "@" in parts[-1]:
            parts[-1], attribute = parts[-1].split("@", 1)
        target = root
        for part in parts:
            target = target.find(part)
            if target is None:
                return {
                    "success": False,
                    "error": f"XML 路径不存在，未修改文件: {raw_path}",
                }
        value = str(op.get("value", ""))
        if attribute:
            target.set(attribute, value)
        else:
            target.text = value
        changed.append(raw_path)

    ET.indent(root, space="  ")
    modified = ET.tostring(root, encoding="unicode")
    if original.lstrip().startswith("<?xml"):
        modified = '<?xml version="1.0" encoding="utf-8"?>\n' + modified
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(modified)
    return {
        "success": True,
        "diff": _generate_diff(original, modified),
        "path": file_path,
        "changed": changed,
    }


def _patch_text(file_path: str, instruction: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        original = f.read()

    patch_ops = _parse_instruction(instruction)
    if not patch_ops:
        return {"success": False, "error": f"无法解析指令: {instruction}"}
    modified = original
    for op in patch_ops:
        key = op.get("key", "")
        value = str(op.get("value", ""))
        pattern = rf"^{re.escape(key)}\s*=\s*.*$"
        replacement = f"{key} = {value}"
        modified, count = re.subn(pattern, replacement, modified, flags=re.MULTILINE)
        if count == 0:
            if modified and not modified.endswith("\n"):
                modified += "\n"
            modified += replacement + "\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(modified)

    return {"success": True, "diff": _generate_diff(original, modified), "path": file_path}


def _parse_instruction(instruction: str) -> list[dict]:
    ops = []
    pattern = r"(\S+)\s*[:=]\s*(\S+)"
    for match in re.finditer(pattern, instruction):
        key = match.group(1)
        value_str = match.group(2)
        try:
            value = json.loads(value_str)
        except (json.JSONDecodeError, ValueError):
            value = value_str
        ops.append({"path": key, "value": value, "key": key})
    return ops


def _generate_diff(before: str, after: str) -> str:
    lines = []
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    max_len = max(len(before_lines), len(after_lines))

    for i in range(max_len):
        b = before_lines[i] if i < len(before_lines) else ""
        a = after_lines[i] if i < len(after_lines) else ""
        if b != a:
            if b:
                lines.append(f"- {b}")
            if a:
                lines.append(f"+ {a}")

    return "\n".join(lines)
