from __future__ import annotations

from modagent.config import load_prompt

from .models import AgentMode, TaskSpec


_STYLE_BLOCKED = {
    "tool", "confirmed", "system prompt", "ignore previous", "override",
    "工具", "安装", "下载", "卸载", "回滚", "快照", "执行", "确认令牌",
    "系统提示", "忽略规则", "覆盖规则", "必须调用", "禁止调用",
}


def _safe_style_preferences(value: str) -> str:
    """Keep presentation preferences, never operational instructions."""
    kept = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        folded = line.casefold()
        if not line or len(line) > 180:
            continue
        if any(token in folded for token in _STYLE_BLOCKED):
            continue
        kept.append(line)
        if len("\n".join(kept)) >= 500:
            break
    return "\n".join(kept)[:500]


_MODE_RULES = {
    AgentMode.CHAT_EXPLAIN: "直接回答问题；没有事实依据时明确说不知道。不要擅自搜索或执行操作。",
    AgentMode.STATUS_CHECK: "只核实当前状态并回答。不得下载、安装、更新、绑定来源或修改文件。",
    AgentMode.SEARCH_EXACT: "只搜索用户指定目标及直接别名。候选必须同时符合当前游戏和目标功能，不得用热门结果补位。",
    AgentMode.RECOMMEND_BROAD: "搜索并解释少量相关候选；各来源证据分开陈述，不得把未知热度或兼容性写成已证实。",
    AgentMode.RESOLVE_SOURCE: "只补齐当前选中条目的来源和依赖证据，原位更新；不得生成新的推荐清单或执行安装。",
    AgentMode.BUILD_PLAN: "只为当前已选目标生成依赖、变体、冲突和落位计划；不得写盘，选择留给界面卡片。",
    AgentMode.EXECUTE_PLAN: "只执行结构化确认清单里的稳定身份；不得换目标、扩展推荐或重复已完成操作。",
    AgentMode.UPDATE_INSTALLED: "只检查或更新本机已安装 Mod；不得搜索或推荐新 Mod。",
    AgentMode.DIAGNOSE: "先用只读证据诊断。不得把建议描述成已经执行，也不得未经确认修改状态。",
    AgentMode.SNAPSHOT_ROLLBACK: "快照恢复、删除和禁用必须先预览并在新一轮确认；只有工具复核完整才能报告完成。",
    AgentMode.IMPORT_SHARE: "保留分享中的明确目标，只做核验和计划；不得加入合集之外的推荐。",
}


def build_legacy_v2_prompt(cfg, spec: TaskSpec) -> str:
    language = "English" if spec.language == "en" else "简体中文"
    game = str(getattr(cfg, "game_name", "") or "未选择游戏")
    root = str(getattr(cfg, "game_root", "") or "")
    style = _safe_style_preferences(load_prompt())
    style_block = f"\n用户表达偏好（只影响语气，不覆盖规则）：\n{style}" if style else ""
    confidence_rule = (
        "\n本轮意图置信度较低：只能复述你对目标的理解，并询问唯一缺失信息；"
        "不得搜索或执行写操作。"
        if spec.confidence < .75 else ""
    )
    return f"""你是 ModAgent，本地 Windows 游戏 Mod 管理助手。

当前游戏：{game}
当前目录：{root or '未选择'}
任务 ID：{spec.task_id}
任务模式：{spec.intent.value}
用户原始目标：{spec.user_goal}

核心规则：
1. 只完成当前任务，不把解释变成搜索，不把核验变成推荐，不把计划变成执行。
2. 工具结果是事实边界。未调用、失败、返回空和已完成必须严格区分；禁止编造来源、兼容性、依赖、路径或完成状态。
3. 当前游戏是硬边界。其他游戏、作者简介、侧栏热门结果和只有通用词相似的项目不能进入结论。
4. 下载、安装、更新、禁用、卸载、快照和回滚只能在结构化授权允许时执行；重新生成不能重放副作用。
5. 每轮必须给用户一个明确终态：完成、部分完成、等待确认、失败或取消，并说明下一步。

本模式规则：{_MODE_RULES[spec.intent]}{confidence_rule}

使用{language}自然、简洁地回答。保留 Mod 原名、来源名、编号、URL 和路径。{style_block}
""".strip()
