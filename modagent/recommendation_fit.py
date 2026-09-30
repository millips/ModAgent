"""Evidence-based goal checks, separate from detail and installation readiness.

Source text is data, never an instruction. Unknown goals remain reviewable but
do not receive a fabricated match or automatic selection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from functools import lru_cache


FACETS = {
    'information': (r'更多信息|信息(?:显示|展示|增强)|读到.*信息|鬼魂信息|证据.*(?:显示|筛选)|\b(?:information|stats|ghost info|informative)\b',
                    r'\b(?:timer|timers|bpm|ghost speed|evidence|information display|information overlay|ghost information)\b|计时|证据|鬼魂速度|鬼速|信息(?:显示|展示)|状态显示|(?:显示|展示).{0,24}(?:属性|生命|护甲|数值|信息)|\b(?:display\w*|show\w*|visualiz\w*|monitor\w*)\b[^.!?;]{0,70}\b(?:stats|statistics|health|armor|information)\b|\b(?:stats|statistics)\s+(?:display|overlay|readout)\b'),
    'interface': (r'\b(?:ui|hud|interface|overlay)\b|界面|覆盖层',
                  r'\b(?:ui|hud|interface|overlay|overlays|panel|readability|font)\b|界面|覆盖层|面板|可读性|字体'),
    'money': (r'\b(?:money|currency|gold|coins?|cash)\b|金钱|金币|钱不够|没钱|一点钱',
              r'\b(?:money|currency|gold|coins?|cash)\b|金钱|金币|货币'),
    'performance': (r'\b(?:fps|performance|stutter)\b|帧率|卡顿|性能优化',
                    r'\b(?:fps|performance|stutter|optimization)\b|帧率|卡顿|性能优化'),
    'appearance': (r'换皮|贴图|服装|外观|\b(?:skin|skins|outfit|outfits|texture|textures|cosmetic)\b',
                   r'换皮|贴图|服装|外观|\b(?:skin|skins|outfit|outfits|texture|textures|cosmetic|replacer)\b'),
}
FEATURES = {
    'timer': r'\btimers?\b|计时',
    'evidence': r'\bevidence\b|证据',
    'ghost_speed': r'\b(?:bpm|ghost speed|ghost pacer)\b|鬼速|鬼魂速度',
    'readability': r'\b(?:readability|font|contrast|scal(?:e|ing))\b|字体|可读性|对比度|缩放',
}


@dataclass(frozen=True)
class GoalRequirements:
    """Read-only interpretation shared by matching and search convergence.

    Deliberately bounded vocabulary, not a general semantic classifier. Keep
    the original goal; unknown requirements never grant an automatic match.
    This object confers no installation permission.
    """
    original_goal: str
    required: tuple[str, ...]
    excluded: tuple[str, ...]
    required_features: tuple[str, ...]
    requested_count: int | None
    exhaustive: bool
    modifies_money: bool

    def to_dict(self):
        return asdict(self)


@lru_cache(maxsize=128)
def compile_goal(goal: str) -> GoalRequirements:
    negative = re.compile(
        r'(?:不要|不需要|不想要|排除|\bwithout\s+|\bno\s+)(?:(?!但是|但要|只要|\bbut\b)[^，,。;；.!?])*', re.I)
    excluded_text = ' '.join(m.group() for m in negative.finditer(goal))
    positive_goal = negative.sub(' ', goal)
    required = tuple(key for key, (query, _) in FACETS.items() if re.search(query, positive_goal, re.I))
    excluded = tuple(key for key, (query, _) in FACETS.items() if re.search(query, excluded_text, re.I))
    features = tuple(key for key, pattern in FEATURES.items() if re.search(pattern, positive_goal, re.I))
    count_match = re.search(r'(\d+|[一二三四五六七八九十两]+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:个|款|种|项|mods?\b|options?\b|tools?\b|candidates?\b)', positive_goal, re.I)
    count = None
    if count_match:
        raw = count_match.group(1).lower()
        words = dict(zip('one two three four five six seven eight nine ten'.split(), range(1, 11)))
        digits = dict(zip('一二三四五六七八九', range(1, 10))) | {'两': 2}
        if raw.isascii() and raw.isdigit():
            count = int(raw)
        elif raw in words or raw in digits:
            count = words.get(raw, digits.get(raw))
        elif re.fullmatch(r'[一二三四五六七八九两]?十[一二三四五六七八九]?', raw):
            left, right = raw.split('十')
            count = digits.get(left, 1) * 10 + digits.get(right, 0)
    # Unparsed quantity expressions must not prematurely stop the search.
    exhaustive = count is not None or bool(re.search(
        r'\d|[一二三四五六七八九十两百千]+\s*(?:个|款|种)|全部|所有|尽可能|all\b|as many|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|several)\s+(?:mods?|options?|tools?|candidates?)\b',
        positive_goal, re.I))
    return GoalRequirements(goal, required, excluded, features, count, exhaustive,
                            bool('money' in required and re.search(r'修改|无限|增加|\b(?:edit|modify|unlimited|trainer|cheat)\b', positive_goal, re.I)))


def assess_goal(item: dict, goal: str | GoalRequirements) -> dict:
    # Do not use owner, URL, category, downloads, generated reasons or tags as
    # functional evidence. Keep sentences so negations cannot count positively.
    requirements = goal if isinstance(goal, GoalRequirements) else compile_goal(goal)
    # A title is an identity hint, not evidence of an implemented feature.
    text = ' '.join(str(item.get(k) or '') for k in ('summary', 'description', 'content'))
    text = re.sub(r'<[^>]+>|\[/?[a-z][^\]]*\]', ' ', text, flags=re.I)
    sentences = re.split(r'(?<=[.!?。！？;；])\s*|\n', text)
    negative_evidence = re.compile(
        r'\b(?:does not|doesn.t|planned|coming soon)\b|\b(?:no|not|without)\s+(?:any\s+)?(?:information|timers?|evidence|hud|ui|stats)\b|不提供|不包含|不增加|不显示|尚未|即将', re.I)
    positive = ' '.join(s for s in sentences if not negative_evidence.search(s))
    facets = list(requirements.required)
    # Information tools may implement their interface as an overlay, not a UI
    # replacement. Both satisfy UI+information; a texture edit alone does not.
    matched = [key for key in facets if re.search(FACETS[key][1], positive, re.I)]
    if 'money' in matched and requirements.modifies_money and not re.search(
            r'(?:\b(?:edit|modify|increase|unlimited|infinite|add)\b|修改|增加|无限).{0,48}(?:\b(?:money|currency|gold|coins?|cash)\b|金钱|金币|货币)|(?:金钱|金币|货币).{0,12}(?:修改|增加|无限)', positive, re.I):
        matched.remove('money')
    missing = [key for key in facets if key not in matched]
    if 'information' in matched and 'interface' in missing:
        missing.remove('interface')
        matched.append('interface')
    features = [key for key, pattern in FEATURES.items() if re.search(pattern, positive, re.I)]
    missing_features = [key for key in requirements.required_features if key not in features]
    excluded_matches = [key for key in requirements.excluded if re.search(FACETS[key][1], positive, re.I)]
    cosmetic_only = bool(re.search(r'仅.*(?:贴图|纹理)|only.*(?:textures?|cosmetic)|(?:textures?|cosmetic).*only', text, re.I))
    explicit_denial = any(negative_evidence.search(s) and re.search(FACETS[key][1], s, re.I)
                          for key in missing for s in sentences)
    rejected = bool(excluded_matches) or explicit_denial or (cosmetic_only and 'information' in facets)
    status = 'mismatch' if rejected else 'matched' if facets and not missing and not missing_features else 'unconfirmed'
    proof = []
    for key in matched:
        for sentence in sentences:
            if sentence and sentence in positive and re.search(FACETS[key][1], sentence, re.I):
                if sentence.strip() not in proof:
                    proof.append(sentence.strip()[:220])
                break
    return {'status': status, 'requested': facets, 'matched': matched, 'missing': missing,
            'excluded_matches': excluded_matches, 'missing_features': missing_features,
            'evidence': proof[:3], 'features': features,
            'alternative_group': 'information_overlay' if 'information' in matched and re.search(r'overlay|覆盖层', positive, re.I) else ''}


def apply_selection(items: list[dict], requirements: GoalRequirements | None = None) -> None:
    """Prefer verified evidence coverage; overlapping implementations are choices.

    This is not a claim of incompatibility. Users can explicitly select both.
    Unchanged legacy callers without a goal retain their previous behavior.
    """
    if not any('goal_fit' in item for item in items):
        return
    groups: dict[str, list[dict]] = {}
    for item in items:
        item['default_selected'] = False
        fit = item.get('goal_fit') or {}
        if group := fit.get('alternative_group'):
            groups.setdefault(group, []).append(item)
    ranked = sorted(items, key=lambda i: (
        -int(bool(i.get('installable'))), -len((i.get('goal_fit') or {}).get('features', [])),
        str(i.get('selection_key', ''))))
    chosen_groups = set()
    count = 0
    limit = min(4, max(0, requirements.requested_count)) if requirements and requirements.requested_count is not None else 4
    for item in ranked:
        fit = item.get('goal_fit') or {}
        group = fit.get('alternative_group', '')
        ready = item.get('installable') and fit.get('status') == 'matched' and not item.get('is_prerequisite')
        if ready and count < limit and (not group or group not in chosen_groups):
            item['default_selected'] = True
            count += 1
            if group:
                chosen_groups.add(group)
        item['selection_reason'] = ('依据功能证据预选；仍需你确认计划' if item['default_selected']
                                    else '未预选：请核对功能匹配、重复功能或安装条件')
        if group and len(groups[group]) > 1:
            item['alternative_names'] = [x['name'] for x in groups[group] if x is not item]
            item['selection_reason'] = ('同类方案中优先预选此项，功能证据覆盖更多或相同；' if item['default_selected'] else '作为同类替代方案保留，未默认叠加；') + '功能重叠不等于已证实冲突，可查看差异后手动选择'


def enough_alternatives(payload: dict, goal: str) -> bool:
    """Stop expanding a focused information-overlay comparison once verified.

    Never short-circuit a request for a specific count or an open-ended list.
    Other task types retain their search budgets.
    """
    requirements = compile_goal(goal)
    if requirements.exhaustive:
        return False
    rows = payload.get('recommendations') or []
    identities = set()
    for row in rows:
        fit = assess_goal(row, requirements)
        if row.get('_detail_verified') and fit['status'] == 'matched' and fit['alternative_group']:
            identities.add(str(row.get('mod_id') or row.get('url') or ''))
    return len(identities - {''}) >= 2
