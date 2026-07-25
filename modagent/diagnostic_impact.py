"""User-facing semantic impact and diagnostic planning helpers.

The file-operation layer knows *how* to disable a mod.  This module explains
what that action means to a player, why it is being proposed, and what the
next diagnostic branch should be.  It deliberately uses broad, reusable role
classification rather than game-specific hard-coded plans.
"""
from __future__ import annotations

import json
import re
from typing import Iterable


_ROLE_RULES = (
    ("framework", ("framework", "loader", "hook", "bepinex", "ue4ss", "repolib", "library", "runtime", "api")),
    ("appearance_system", ("costume changer", "wardrobe manager", "appearance menu", "outfit manager")),
    ("appearance", ("costume", "outfit", "dress", "clothing", "skin", "hair", "makeup", "cosmetic", "服装", "外观")),
    ("interface", ("interface", "hud", "menu", "minimap", "ui ", "overlay", "界面", "地图")),
    ("performance", ("performance", "fps", "latency", "stutter", "optimization", "性能", "帧率")),
    ("gameplay", ("gameplay", "difficulty", "combat", "revive", "upgrade", "cheat", "玩法", "战斗")),
    ("audio", ("audio", "sound", "music", "voice", "音效", "音乐")),
)

_ROLE_LABELS = {
    "framework": "加载框架/前置底座",
    "appearance_system": "外观与换装系统",
    "appearance": "外观内容",
    "interface": "界面功能",
    "performance": "性能调整",
    "gameplay": "玩法功能",
    "audio": "声音内容",
    "unknown": "独立 Mod 功能",
}

_LOSS_TEMPLATES = {
    "framework": "依赖它加载的 Mod 将无法运行；相关菜单、脚本或扩展也会一起消失。",
    "appearance_system": "游戏内换装、服装切换或外观管理能力将暂时不可用，依赖它的服装内容也不会显示。",
    "appearance": "这项 Mod 提供的服装、模型或外观将暂时不再显示。",
    "interface": "这项 Mod 提供的界面、信息面板或快捷交互将暂时不可用。",
    "performance": "这项 Mod 的性能、画面或延迟优化将暂时停止生效。",
    "gameplay": "这项 Mod 改变的玩法、规则或便利功能将暂时恢复为未安装时的状态。",
    "audio": "这项 Mod 提供的音乐、语音或音效将暂时不再播放。",
    "unknown": "这项 Mod 提供的功能将暂时不可用；由于维护页信息不足，具体影响需要在禁用后复测确认。",
}


def _files(mod) -> list[str]:
    try:
        values = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
        return [str(value) for value in values] if isinstance(values, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _binding_text(binding: dict | None) -> str:
    binding = binding or {}
    metadata = binding.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {"description": metadata}
    bits = [binding.get("source_key"), binding.get("source_url")]
    if isinstance(metadata, dict):
        bits.extend(metadata.get(key) for key in ("name", "summary", "description", "category"))
    return " ".join(str(bit or "") for bit in bits)


def classify_mod(mod, binding: dict | None = None) -> dict:
    text = " ".join([str(getattr(mod, "name", "") or ""), _binding_text(binding), *(_files(mod)[:80])]).casefold()
    # Avoid treating every DLL as a framework; names/descriptions are stronger evidence.
    for role, keywords in _ROLE_RULES:
        matches = [keyword for keyword in keywords if keyword.casefold() in text]
        if matches:
            confidence = "high" if any(keyword in str(getattr(mod, "name", "")).casefold() for keyword in matches) else "medium"
            return {"role": role, "role_label": _ROLE_LABELS[role], "confidence": confidence,
                    "evidence": matches[:3]}
    return {"role": "unknown", "role_label": _ROLE_LABELS["unknown"], "confidence": "low", "evidence": []}


def build_disable_impact(target, active_plan: Iterable, already_disabled: Iterable,
                         all_installed: Iterable, bindings: dict[str, dict] | None = None) -> dict:
    bindings = bindings or {}
    active_plan = list(active_plan)
    already_disabled = list(already_disabled)
    affected = []
    for mod in active_plan:
        role = classify_mod(mod, bindings.get(str(mod.id)))
        affected.append({
            "id": str(mod.id), "name": mod.name, **role,
            "functionality_lost": _LOSS_TEMPLATES[role["role"]],
        })

    affected_ids = {str(mod.id) for mod in active_plan}
    inactive_ids = {str(mod.id) for mod in already_disabled}
    retained = []
    for mod in all_installed:
        if str(mod.id) in affected_ids or str(mod.id) in inactive_ids:
            continue
        role = classify_mod(mod, bindings.get(str(mod.id)))
        retained.append({"id": str(mod.id), "name": mod.name, "role_label": role["role_label"]})

    target_role = classify_mod(target, bindings.get(str(target.id)))
    cascade = max(0, len(active_plan) - 1)
    if not active_plan:
        recommendation = "目标及其依赖项已经处于禁用状态，无需再次修改文件；应直接继续验证或选择下一项排查。"
    elif target_role["role"] == "framework" and cascade:
        recommendation = "这是影响范围较大的底座级操作。若日志没有直接指向底座，优先禁用最末端的可疑功能 Mod，能保留更多现有能力。"
    else:
        recommendation = "这是可逆的隔离测试：先只移除这组功能并复测；若故障消失，再检查版本、依赖或兼容说明，而不是直接卸载。"

    return {
        "summary": f"将暂时停用 {len(active_plan)} 个当前启用的 Mod；不会卸载或删除文件。",
        "player_impact": affected,
        "already_inactive": [
            {"id": str(mod.id), "name": mod.name, "note": "已经禁用，本次不会重复操作"}
            for mod in already_disabled
        ],
        "retained": retained[:12],
        "why_this_step": "用最小、可恢复的变更验证故障是否来自这组 Mod，避免直接重装或破坏现有配置。",
        "recommendation": recommendation,
        "reversible": True,
        "recovery": "可用“启用 Mod”按原依赖顺序恢复；禁用过程不删除 Mod 文件。",
        "next_if_fixed": "保持当前项禁用，核对其维护页、游戏版本、前置依赖和已知冲突，再决定更新、替换或恢复。",
        "next_if_not_fixed": "先恢复本次变更，再按日志证据选择下一组；不要在故障未变化时继续扩大禁用范围。",
    }


def build_diagnostic_strategy(result: dict, installed_mods: Iterable,
                              bindings: dict[str, dict] | None = None) -> dict:
    """Turn raw log attribution into a ranked, bounded investigation plan."""
    mods = list(installed_mods or [])
    bindings = bindings or {}
    named = {re.sub(r"\W+", "", str(mod.name).casefold()): mod for mod in mods}
    evidence_names = []
    for finding in result.get("findings") or []:
        evidence_names.extend(str(item.get("mod") or "") for item in finding.get("broken_mods") or [])
        evidence_names.extend(str(item.get("name") or "") for item in finding.get("attributed_mods") or [])

    candidates = []
    for evidence_name in evidence_names:
        token = re.sub(r"\W+", "", evidence_name.casefold())
        mod = next((value for key, value in named.items() if token and (token in key or key in token)), None)
        if not mod or any(item["id"] == str(mod.id) for item in candidates):
            continue
        role = classify_mod(mod, bindings.get(str(mod.id)))
        candidates.append({"id": str(mod.id), "name": mod.name, **role,
                           "reason": "框架日志直接提及或明确记录了加载失败"})

    candidates.sort(key=lambda item: (item["role"] == "framework", item["confidence"] != "high"))
    return {
        "evidence_level": "direct" if candidates else "insufficient",
        "ranked_candidates": candidates,
        "research_before_change": [
            "核对候选 Mod 的维护页、目标游戏版本、必需前置与近期已知问题",
            "确认日志是在本次故障复现后生成，而不是旧记录",
        ],
        "isolation_policy": "优先处理日志直接指向、影响范围最小的末端 Mod；加载器/框架放在后面，除非日志明确指向它。",
        "stop_condition": "每次只执行一组已确认的可逆变更并复测；结果没有变化就恢复，再进入下一组。",
        "fallback": "没有直接证据时先补采日志和版本信息，不应盲目批量禁用或重装。",
    }
