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
        elif ext in (".xml", ".esp", ".esm"):
            return {"success": False, "error":
                    f"{ext} 补丁尚未实现，未修改文件；请使用专用工具（如 xEdit）"}
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

    modified = original

    return {"success": True, "diff": _generate_diff(original, modified), "path": file_path,
            "warning": "XML/ESP/ESM 补丁为占位实现，需要基于 xEdit 格式的解析器"}


def _patch_text(file_path: str, instruction: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        original = f.read()

    patch_ops = _parse_instruction(instruction)
    modified = original
    for op in patch_ops:
        key = op.get("key", "")
        value = str(op.get("value", ""))
        pattern = rf"^{re.escape(key)}\s*=\s*.*$"
        replacement = f"{key} = {value}"
        modified = re.sub(pattern, replacement, modified, flags=re.MULTILINE)

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
