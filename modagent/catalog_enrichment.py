"""Cached, evidence-aware Chinese descriptions for the installed Mod catalogue."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


_EVIDENCE_NAMES = {
    "manifest.json",
    "everest.yaml",
    "everest.yml",
    "readme.md",
    "readme.txt",
    "description.txt",
}


def _inside_allowed_root(path: str, allowed_roots: list[str]) -> bool:
    try:
        target = os.path.normcase(os.path.realpath(path))
        for root in allowed_roots:
            if not root:
                continue
            base = os.path.normcase(os.path.realpath(root))
            if os.path.commonpath([target, base]) == base:
                return True
    except (OSError, ValueError):
        return False
    return False


def _installed_files(mod) -> list[str]:
    value = getattr(mod, "files_installed", "[]")
    try:
        files = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(path) for path in files or [] if isinstance(path, str)]


def _manifest_evidence(path: str) -> str:
    try:
        if os.path.getsize(path) > 128 * 1024:
            return ""
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if os.path.basename(path).casefold() == "manifest.json":
        try:
            data = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            values = []
            for key in ("Name", "name", "Description", "description", "Author", "author"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(f"{key}: {value.strip()}")
            if values:
                return "\n".join(values)[:1600]
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"[#>*`|]+", " ", raw).strip()
        if line and not re.fullmatch(r"[-=_\s]+", line):
            lines.append(line)
        if len("\n".join(lines)) >= 1200:
            break
    return "\n".join(lines)[:1600]


def collect_local_evidence(mod, allowed_roots: list[str]) -> str:
    """Read only small, known metadata files already owned by an inventory row."""
    candidates = []
    for path in _installed_files(mod):
        if (
            os.path.basename(path).casefold() in _EVIDENCE_NAMES
            and _inside_allowed_root(path, allowed_roots)
            and os.path.isfile(path)
        ):
            candidates.append(path)
    # Prefer manifests over prose and keep prompt size bounded.
    candidates.sort(key=lambda path: (
        os.path.basename(path).casefold() != "manifest.json",
        len(path),
    ))
    for path in candidates[:3]:
        evidence = _manifest_evidence(path)
        if evidence:
            return evidence
    return ""


def binding_evidence(binding: dict | None) -> str:
    if not binding:
        return ""
    try:
        metadata = json.loads(binding.get("metadata") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    values = []
    for key in (
        "name", "package_name", "description", "summary", "owner",
        "community", "author",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            values.append(f"{key}: {value.strip()}")
    return "\n".join(values)[:1200]


def build_enrichment_inputs(
    mods,
    bindings: dict[str, dict],
    cached: dict[str, dict],
    allowed_roots: list[str],
    force: bool = False,
) -> list[dict]:
    rows = []
    for mod in mods:
        mod_id = str(mod.id)
        local = collect_local_evidence(mod, allowed_roots)
        upstream = binding_evidence(bindings.get(mod_id))
        if local:
            evidence, evidence_kind = local, "local_manifest"
        elif upstream:
            evidence, evidence_kind = upstream, "source_metadata"
        else:
            evidence, evidence_kind = "", "name_inference"
        fingerprint = hashlib.sha256(json.dumps({
            "name": mod.name,
            "version": mod.version,
            "evidence": evidence,
            "binding": {
                key: bindings.get(mod_id, {}).get(key)
                for key in ("source", "source_key", "latest_version")
            },
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        previous = cached.get(mod_id) or {}
        if (
            not force
            and previous.get("localized_name")
            and previous.get("summary")
            and previous.get("source_fingerprint") == fingerprint
        ):
            continue
        rows.append({
            "mod_id": mod_id,
            "name": mod.name,
            "version": mod.version,
            "evidence": evidence,
            "evidence_kind": evidence_kind,
            "source_fingerprint": fingerprint,
        })
    return rows


def _parse_json_object(text: str) -> dict:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        start, end = value.find("{"), value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(value[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return {}


def generate_catalog_notes(client, model: str, rows: list[dict]) -> list[dict]:
    """Generate faithful summaries in one bounded LLM call."""
    if not rows:
        return []
    prompt_rows = [{
        "mod_id": row["mod_id"],
        "name": row["name"],
        "version": row["version"],
        "evidence_kind": row["evidence_kind"],
        "evidence": row["evidence"],
    } for row in rows[:80]]
    prompt = (
        "为已安装 Mod 管理列表生成简体中文信息。每项返回："
        "localized_name（简短忠实中文名，保留专有名词）和 summary"
        "（一句话说明玩家会获得或改变什么，建议 20-70 个中文字）。"
        "只能使用给出的名称和 evidence。evidence 为空时允许根据名称做保守推测，"
        "但 summary 必须以“可能”开头，不能虚构具体按键、依赖或兼容性。"
        "不要把版本号当成功能。只返回 JSON："
        '{"items":[{"mod_id":"原值","localized_name":"中文名",'
        '"summary":"功能简介"}]}。\n'
        + json.dumps(prompt_rows, ensure_ascii=False)
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是严谨的游戏 Mod 中文资料整理助手；证据不足时必须明确不确定。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    content = response.choices[0].message.content or ""
    parsed = _parse_json_object(content)
    returned = {
        str(item.get("mod_id")): item
        for item in parsed.get("items") or []
        if isinstance(item, dict) and item.get("mod_id") is not None
    }
    notes = []
    for row in rows[:80]:
        item = returned.get(row["mod_id"]) or {}
        localized_name = str(item.get("localized_name") or row["name"]).strip()[:120]
        summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()[:360]
        if not summary:
            continue
        if row["evidence_kind"] == "name_inference" and not summary.startswith("可能"):
            summary = "可能" + summary
        notes.append({
            "mod_id": row["mod_id"],
            "localized_name": localized_name,
            "summary": summary,
            "evidence_kind": row["evidence_kind"],
            "confidence": (
                "high" if row["evidence_kind"] == "local_manifest"
                else "medium" if row["evidence_kind"] == "source_metadata"
                else "low"
            ),
            "source_fingerprint": row["source_fingerprint"],
        })
    return notes
