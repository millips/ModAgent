"""
ModAgent 汇报事实校验 (P2.4)

作用:在最终汇报出口,校验模型说出口的关键事实是否真的来自本轮工具返回。
针对已实测到的幻觉:模型引用了磁盘/DB 都不存在的快照 ID(如 snap_20260628_124117)。

放置:modagent/report_validator.py

⚠️ 关于 spec 2.4 的坑:
如果"合法来源"只算本轮 tool_results,会误伤合法场景——比如用户自己说
"回滚到 snap_20260627_192709",模型复述这个用户给的 ID 会被当成幻觉。
所以 known-good 集合 = 本轮 tool_results 里的 ID ∪ 输入消息(用户/历史)里出现的 ID。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# 快照 ID 形如 snap_20260627_192709(可带去重后缀 _2)
_SNAP_RE = re.compile(r"snap_\d{8}_\d{6}(?:_\d+)?")
# Windows 绝对路径:盘符:\... ,停在空白/引号/分隔标点/中文
_WINPATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'；;，,。、）)\u4e00-\u9fff]+")
# "12/12" 这类完成计数
_COUNT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _collect_strings(obj, out: list) -> None:
    """递归收集 JSON 结构里的所有字符串叶子。"""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)


@dataclass
class ReportViolation:
    kind: str          # "phantom_snapshot" | "phantom_path" | "count_mismatch"
    value: str
    detail: str = ""


@dataclass
class ValidationResult:
    ok: bool
    violations: list[ReportViolation] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "报告校验通过"
        return "报告校验未通过: " + "; ".join(
            f"[{v.kind}] {v.value} {v.detail}".strip() for v in self.violations
        )


def _gather_text(items) -> str:
    """
    把 tool_results / input messages 拼成大字符串供正则扫描。
    关键:若 content 是 JSON,先解析出字符串叶子再拼,避免路径里的反斜杠被
    JSON 转义成 '\\\\' 而与报告里的单反斜杠对不上(否则真实路径会被误判幻觉)。
    """
    parts: list[str] = []
    for it in items or []:
        if isinstance(it, str):
            s = it
        elif isinstance(it, dict):
            c = it.get("content", "")
            s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        else:
            continue
        parts.append(s)                       # 原文保留(snap_id 等仍可匹配)
        try:                                  # 额外补上解析后的字符串叶子
            _collect_strings(json.loads(s), parts)
        except Exception:
            pass
    return "\n".join(parts)


def _norm_path(p: str) -> str:
    return p.replace("\\", "/").rstrip("/").casefold()


def _known_snapshot_ids(tool_results, input_messages) -> set[str]:
    real = set(_SNAP_RE.findall(_gather_text(tool_results)))
    user_supplied = set(_SNAP_RE.findall(_gather_text(input_messages)))
    return real | user_supplied


def _known_paths(tool_results) -> set[str]:
    return set(_WINPATH_RE.findall(_gather_text(tool_results)))


def validate_report(
    report_text: str,
    tool_results: list,
    input_messages: list | None = None,
    *,
    check_paths: bool = True,
    check_counts: bool = True,
) -> ValidationResult:
    """
    report_text:模型准备发给用户的最终汇报文本。
    tool_results:本轮所有 tool result(dict 或 JSON 字符串都行)。
    input_messages:本轮输入消息(含用户消息 / 压缩历史),用于把用户给的 ID 加入白名单。
    """
    violations: list[ReportViolation] = []

    # 1) 快照 ID:报告里出现、但既不在工具返回、也不在用户输入里 → 幻觉
    good_ids = _known_snapshot_ids(tool_results, input_messages)
    for sid in set(_SNAP_RE.findall(report_text)):
        if sid not in good_ids:
            violations.append(ReportViolation(
                "phantom_snapshot", sid, "未出现在任何工具返回或用户输入中"))

    # 2) 绝对路径:报告里声称的文件路径应能在工具返回里找到出处
    if check_paths:
        good_norm = {_norm_path(gp) for gp in _known_paths(tool_results)}
        for p in set(_WINPATH_RE.findall(report_text)):
            pn = _norm_path(p)
            if not any(pn in gp or gp in pn for gp in good_norm):
                violations.append(ReportViolation(
                    "phantom_path", p, "工具返回中无此路径,疑似编造(尤其 GitHub/第三方下载)"))

    # 3) 完成计数:"N/N 成功"里的分母不应凭空变大(只做保守告警)
    if check_counts:
        for done, total in _COUNT_RE.findall(report_text):
            if done != total:
                # done<total 是正常的部分完成;这里只标记 done>total 的荒谬情况
                if int(done) > int(total):
                    violations.append(ReportViolation(
                        "count_mismatch", f"{done}/{total}", "完成数大于总数"))

    return ValidationResult(ok=not violations, violations=violations)


def build_correction_message(result: ValidationResult) -> dict:
    """校验失败时,注入给 LLM 让它重写汇报的纠偏消息。"""
    return {
        "role": "user",
        "content": (
            "[系统纠偏] 你的汇报包含工具从未返回的内容:"
            + result.summary()
            + "。只允许引用本轮工具的真实返回值。请仅根据真实结果重写这段汇报,"
              "不要提及任何未经工具确认的快照 ID、文件路径或数字。"
              "重要:这是系统内部校验,用户看不到本消息——重写时直接给出正确的汇报本身,"
              "不要提及本次纠偏、不要道歉、不要说\"你说得对\"或\"我不该编造\"之类的话。"
        ),
    }


_SEARCH_TOOL_SOURCE = {
    "nexus_search": "nexus",
    "workshop_search": "workshop",
    "thunderstore_search": "thunderstore",
    "github_search": "github",
    "gamebanana_search": "gamebanana",
}
_SOURCE_LABELS = {
    "nexus": ("nexus",),
    "workshop": ("创意工坊", "workshop"),
    "thunderstore": ("thunderstore",),
    "github": ("github",),
    "gamebanana": ("gamebanana",),
}
_SEARCHED_WORDS = ("已搜索", "搜过", "查过", "已查", "实际调用", "翻了")
_ABSENCE_WORDS = (
    "没有专区", "无专区", "未收录", "根本没有", "不存在",
    "没有任何mod", "没有任何 mod", "全网没有",
)
_AVAILABILITY_WORDS = ("专区存在", "工坊存在", "支持创意工坊", "已经开了")
_ALL_SOURCE_WORDS = ("所有来源", "全部来源", "所有渠道", "全网", "翻了一遍")


def _search_ledger(persist: list[dict]) -> dict:
    """Build a source ledger from real tool calls and their paired results."""
    calls = {}
    for message in persist or []:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            calls[call.get("id", "")] = fn.get("name", "")

    ledger = {
        "attempted": set(),
        "consulted": set(),
        "empty": set(),
        "failed": set(),
        "skipped": set(),
        "confirmed_unavailable": set(),
        "confirmed_available": set(),
    }
    for message in persist or []:
        if message.get("role") != "tool":
            continue
        tool_name = calls.get(message.get("tool_call_id", ""), "")
        source = _SEARCH_TOOL_SOURCE.get(tool_name)
        try:
            payload = json.loads(message.get("content") or "{}")
        except Exception:
            payload = {}

        if tool_name == "mod_recommend" and isinstance(payload, dict):
            ledger["attempted"].update(payload.get("sources_attempted") or [])
            ledger["consulted"].update(payload.get("sources_consulted") or [])
            ledger["empty"].update(payload.get("sources_empty") or [])
            ledger["failed"].update((payload.get("sources_failed") or {}).keys())
            ledger["skipped"].update((payload.get("sources_skipped") or {}).keys())
            for name, state in (payload.get("source_evidence") or {}).items():
                if isinstance(state, dict) and state.get("status") == "unavailable_confirmed":
                    ledger["confirmed_unavailable"].add(name)
                if isinstance(state, dict) and state.get("status") == "available":
                    ledger["confirmed_available"].add(name)
            continue
        if not source:
            continue
        ledger["attempted"].add(source)
        if isinstance(payload, dict) and (
            payload.get("error") or payload.get("searched") is False
        ):
            ledger["failed"].add(source)
        else:
            ledger["consulted"].add(source)
            if (
                isinstance(payload, dict)
                and payload.get("status") == "search_empty"
            ) or payload == []:
                ledger["empty"].add(source)
    return ledger


def _has_explicit_nexus_restriction_evidence(persist: list[dict]) -> bool:
    calls = {}
    for message in persist or []:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                calls[call.get("id", "")] = (
                    (call.get("function") or {}).get("name", "")
                )
        elif (
            message.get("role") == "tool"
            and calls.get(message.get("tool_call_id", ""))
            in {"nexus_get_detail", "mod_download"}
        ):
            content = (message.get("content") or "").casefold()
            if any(marker in content for marker in (
                "adult content", "content blocking",
                "permission denied", "http 403", "status 403",
            )):
                return True
    return False


def validate_search_report(report_text: str, persist: list[dict]) -> ValidationResult:
    """Reject source claims that are stronger than this turn's tool evidence."""
    text = (report_text or "").casefold()
    ledger = _search_ledger(persist)
    violations: list[ReportViolation] = []

    for source, labels in _SOURCE_LABELS.items():
        mentioned = any(label.casefold() in text for label in labels)
        if not mentioned:
            continue
        says_searched = any(word.casefold() in text for word in _SEARCHED_WORDS)
        if says_searched and source not in ledger["consulted"]:
            violations.append(ReportViolation(
                "unconsulted_source", source,
                "回复声称已搜索，但本轮工具证据中该来源未成功查询"))
        says_absent = any(word.casefold() in text for word in _ABSENCE_WORDS)
        for match in re.finditer(r"没有[^，。；;\n]{0,24}(?:mod|模组)", text, re.IGNORECASE):
            fragment = match.group(0)
            if not any(word in fragment for word in ("没搜到", "没有搜到", "未搜到")):
                says_absent = True
        if says_absent and source not in ledger["confirmed_unavailable"]:
            violations.append(ReportViolation(
                "unsupported_absence", source,
                "空结果、跳过或探测失败不能证明平台/专区/Mod 不存在"))
        says_available = any(word.casefold() in text for word in _AVAILABILITY_WORDS)
        if says_available and source not in ledger["confirmed_available"]:
            violations.append(ReportViolation(
                "unsupported_availability", source,
                "Steam appid 或一次搜索尝试不能证明平台专区可用"))

    if any(word.casefold() in text for word in _ALL_SOURCE_WORDS):
        all_sources = set(_SOURCE_LABELS)
        if ledger["consulted"] != all_sources:
            violations.append(ReportViolation(
                "unsupported_all_sources", ",".join(sorted(ledger["consulted"])),
                "并未成功查询全部来源"))

    causal_claim = (
        any(word in text for word in ("成人内容", "adult content", "nsfw"))
        and any(word in text for word in (
            "受限", "限制", "过滤", "攔", "拦", "权限",
            "需要登录", "绕不过", "content blocking",
        ))
    )
    if causal_claim and not _has_explicit_nexus_restriction_evidence(persist):
        violations.append(ReportViolation(
            "unsupported_error_cause", "nexus",
            "404 或详情读取失败不能证明成人内容过滤、登录限制、下架或权限问题"))

    return ValidationResult(ok=not violations, violations=violations)


def build_search_correction_message(result: ValidationResult) -> dict:
    return {
        "role": "user",
        "content": (
            "[系统纠偏] 搜索汇报与本轮真实工具证据不一致："
            + result.summary()
            + "。请按实际来源状态重写：未调用=未查询；失败=查询失败；"
              "空结果=本次未搜到。不得把这些情况写成平台未收录、专区不存在、"
              "全网没有或所有来源都已搜索。只重写最终汇报，不要提及本次纠偏。"
        ),
    }


def build_search_fallback(persist: list[dict]) -> str:
    """Deterministic safe report used when the model ignores correction."""
    ledger = _search_ledger(persist)
    labels = {
        "nexus": "Nexus",
        "workshop": "Steam 创意工坊",
        "thunderstore": "Thunderstore",
        "github": "GitHub",
        "gamebanana": "GameBanana",
    }
    lines = ["本轮搜索结果按实际工具记录汇总："]
    for source in sorted(ledger["consulted"]):
        if source in ledger["empty"]:
            lines.append(f"- {labels.get(source, source)}：已查询，本次未搜到匹配结果。")
        else:
            lines.append(f"- {labels.get(source, source)}：已成功查询，请以工具返回结果为准。")
    for source in sorted(ledger["failed"]):
        lines.append(f"- {labels.get(source, source)}：查询失败，不能据此判断是否存在相关 Mod。")
    for source in sorted(ledger["skipped"] - ledger["consulted"] - ledger["failed"]):
        lines.append(f"- {labels.get(source, source)}：本轮未查询。")
    lines.append("以上空结果仅代表本次搜索未命中，不能证明平台未收录、专区不存在或全网没有相关 Mod。")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 状态断言校验(v1)——干掉"该查状态却用记忆瞎报"的幻觉
#
# 三闸门,全部命中才判定为"该拦":
#   ① 意图闸:用户在【查询状态】(对象词 + 疑问/列举词 双命中)
#   ② 断言闸:agent 回答里给出了具体【数量/存在性】断言
#   ③ 无来源闸:本轮没有调用任何【状态查询工具】(get_installed / snapshot_list)
#
# 关键词表放在最上面,方便随时增删(你比谁都清楚用户真实怎么问)。
# ══════════════════════════════════════════════════════════════════════

# —— 意图闸:对象词(指向什么东西)——
STATE_OBJECT_WORDS = [
    "快照", "回滚", "版本", "之前那版", "之前的那版", "上一版",
    "模组", "mod", "插件", "补丁", "cns", "ue4ss", "社区模式", "自定", "模块",
    "已安装", "安装了", "装了", "装的", "框架", "加载器",
]

# —— 意图闸:疑问 / 列举词(在查询)——
# 注意:不放裸"是什么"——"CNS是什么"是概念提问,不是状态查询,不该拦
STATE_QUERY_WORDS = [
    "几个", "多少", "哪些", "有没有", "有几", "装了吗", "装了没", "装没装",
    "列一下", "列个", "看下", "看一下", "查一下", "查查", "现在有",
    "都有啥", "都有什么", "有哪些", "列表", "清单",
    "什么版本", "版本是什么", "哪个版本", "版本多少", "什么版",
]

# —— 状态查询工具:调了这些才算"有真实来源" ——
# 不只 get_installed/snapshot_list:版本、依赖、说明类信息,
# nexus_get_detail / read_readme 等同样是合法证据来源(否则会误伤"查了详情页再答版本"的健康行为)
STATE_QUERY_TOOLS = {
    "get_installed", "snapshot_list",
    "nexus_get_detail", "read_readme", "conflict_check",
    "scan_existing_mods", "nexus_search",
}

# —— 断言闸:回答里出现"数量/存在性/版本"断言的特征 ——
# 数量:数字紧跟对象词(如 "34 个 mod" / "12 个快照")
_COUNT_ASSERT_RE = re.compile(
    r"\d+\s*(?:个|条|款|项)?\s*(?:mod|模组|插件|补丁|快照|版本|模块)", re.IGNORECASE)
# 存在性:对象/框架 + "在/装了/已安装/都在"
_EXIST_ASSERT_RE = re.compile(
    r"(?:ue4ss|cns|框架|环境|mod|模组|插件|快照)[^。;,\n]{0,6}"
    r"(?:都在|已安装|安装了|装了|在的|存在|齐全|健康)", re.IGNORECASE)
# 版本:「版本是/为 vX」或独立的 vX.Y 版本号断言(病样#1:"记录版本是 v1.3")
_VER_ASSERT_RE = re.compile(
    r"(?:版本|version)[^\n。;,]{0,6}?(?:是|为|：|:)\s*\**v?\d"
    r"|(?<![\w.])v\d+(?:\.\d+)+", re.IGNORECASE)


def _hit(text: str, words: list) -> str | None:
    low = (text or "").lower()
    for w in words:
        if w.lower() in low:
            return w
    return None


def is_state_query(user_msg: str) -> bool:
    """意图闸:用户是否在【查询状态】= 对象词 与 疑问/列举词 同时命中。"""
    return bool(_hit(user_msg, STATE_OBJECT_WORDS) and _hit(user_msg, STATE_QUERY_WORDS))


def has_state_assertion(reply: str) -> bool:
    """断言闸:回答里是否给出了具体的数量/存在性/版本断言。"""
    r = reply or ""
    return bool(_COUNT_ASSERT_RE.search(r) or _EXIST_ASSERT_RE.search(r)
                or _VER_ASSERT_RE.search(r))


def called_state_tool(tool_names) -> bool:
    """无来源闸的反面:本轮是否调用了状态查询工具。"""
    return any(n in STATE_QUERY_TOOLS for n in (tool_names or []))


def check_unsourced_state(user_msg: str, reply: str, tool_names_this_turn: list) -> dict:
    """
    综合三闸门。返回判定详情(供拦截决策 + 记进 trace)。
    should_block=True 表示:用户在查状态、agent 报了具体数字/存在性、却没调工具 → 该拦。
    """
    gate_intent = is_state_query(user_msg)
    gate_assert = has_state_assertion(reply)
    gate_nosrc = not called_state_tool(tool_names_this_turn)
    should_block = gate_intent and gate_assert and gate_nosrc
    return {
        "should_block": should_block,
        "gate_intent": gate_intent,
        "gate_assertion": gate_assert,
        "gate_no_source": gate_nosrc,
        "intent_hit": _hit(user_msg, STATE_OBJECT_WORDS) and _hit(user_msg, STATE_QUERY_WORDS),
    }


def build_state_correction_message() -> dict:
    """拦到后注入给 LLM 的纠偏消息:逼它先调工具再回答。"""
    return {
        "role": "user",
        "content": (
            "[系统纠偏] 用户在询问当前的安装/快照状态,你却在没有调用查询工具的情况下"
            "直接报出了具体数量或存在性结论——这类数字必须来自工具的真实返回,不能凭记忆或上文推断。"
            "请先调用相应的查询工具(查已装 Mod 用 get_installed,查快照用 snapshot_list),"
            "再根据工具的真实返回如实回答。"
            "重要:这是系统内部校验,用户看不到本消息——回答时直接给出查证后的结果,"
            "不要提及本次纠偏、不要道歉、不要说\"你说得对\"之类的话。"
        ),
    }


if __name__ == "__main__":
    # 冒烟自测:python -m modagent.report_validator
    tool_results = [
        {"content": json.dumps({"snapshot_id": "snap_20260627_192709", "files_count": 12})},
        {"content": json.dumps({"filepath": "I:\\cache\\stellarblade\\123_suit.zip"})},
    ]
    inputs = [{"role": "user", "content": "帮我装一下"}]

    r1 = validate_report(
        "已创建快照 snap_20260627_192709,文件在 I:\\cache\\stellarblade\\123_suit.zip",
        tool_results, inputs)
    print("真实引用:", r1.summary())          # 应通过

    r2 = validate_report(
        "已从 GitHub 下好 UE4SS,文件在 I:\\downloads\\gh_UE4SS_v3.0.1.zip;快照 snap_20260628_124117",
        tool_results, inputs)
    print("幻觉引用:", r2.summary())          # 应报 2 处

    r3 = validate_report(
        "回滚到 snap_20991231_235959", tool_results,
        [{"role": "user", "content": "回滚到 snap_20991231_235959"}])
    print("用户给的ID:", r3.summary())         # 应通过(白名单命中)

    print("\n=== 状态断言校验(三闸门)===")
    cases = [
        # (说明, 用户消息, agent回答, 本轮工具, 期望should_block)
        ("你好→顺口报34mod(不该拦)", "你好",
         "你好！当前游戏已经装了 34 个 mod,环境很健康～", [], False),
        ("查mod没调工具(该拦)", "我装了几个mod",
         "你当前一共装了 34 个 mod,大部分是 CNS 服装。", [], True),
        ("查快照没调工具(该拦)", "现在有几个快照了",
         "你目前一共有 22 个快照。", [], True),
        ("查mod且调了工具(不该拦)", "装了哪些mod",
         "根据查询,你装了 34 个 mod:...", ["get_installed"], False),
        ("查存在性没调工具(该拦)", "UE4SS装了吗",
         "UE4SS 和 CNS 框架都在,环境健康。", [], True),
        ("安装意图非查询(不该拦)", "帮我安装CET和UE4SS",
         "好的,我先为你创建快照,然后安装这 2 个 mod。", [], False),
        ("查快照调了snapshot_list(不该拦)", "我快照几个了",
         "你有 22 个快照。", ["snapshot_create", "snapshot_list"], False),
        # —— v0.4 补漏用例(病样#1)——
        ("问版本没调工具(该拦·病样#1)", "ue4ss是什么版本的",
         "你已安装的 Stellar Blade UE4SS 记录版本是 **v1.3**。", [], True),
        ("问版本且调了工具(不该拦)", "cns什么版本",
         "查询到 CNS 版本为 v2.2。", ["get_installed"], False),
        ("概念提问不是状态查询(不该拦)", "CNS是什么",
         "CNS 是 Custom Nanosuit System,一个服装切换框架,游戏内按 N 键使用。", [], False),
        ("查了详情页再答版本(不该拦·v0.4复测样)", "ue4ss是什么版本的",
         "查到了。你装的是 mod_id 2952 v1.3,详情页描述为 Updated RE-UE4SS fork。",
         ["nexus_get_detail", "nexus_search"], False),
    ]
    allok = True
    for desc, um, rep, tools, expect in cases:
        r = check_unsourced_state(um, rep, tools)
        ok = (r["should_block"] == expect)
        allok = allok and ok
        print(f"  [{'✅' if ok else '❌ 错'}] {desc}: block={r['should_block']} "
              f"(意图{int(r['gate_intent'])} 断言{int(r['gate_assertion'])} 无源{int(r['gate_no_source'])})")
    print("状态校验总判定:", "全部通过 ✅" if allok else "有用例未通过 ❌")
