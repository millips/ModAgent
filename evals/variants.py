from __future__ import annotations

from dataclasses import replace

from .core_cases import CORE_CASES, GoldenCase


_TRANSFORMS = (
    lambda text: f"请问，{text}",
    lambda text: f"{text} 麻烦只处理这个目标。",
    lambda text: f"当前游戏已经选好。{text}",
    lambda text: f"用户原话：{text}",
    lambda text: text.replace("？", "?").replace("。", ""),
    lambda text: f"{text}\n不要扩展到别的任务。",
    lambda text: f"我再确认一下：{text}",
    lambda text: f"{text} Please stay on this task.",
    lambda text: f"上下文可能很长，但我现在只问：{text}",
)


def build_variant_suite(size: int) -> list[GoldenCase]:
    """Create deterministic paraphrase/noise variants with stable expectations."""
    target = max(len(CORE_CASES), int(size))
    cases = list(CORE_CASES)
    round_index = 0
    while len(cases) < target:
        transform = _TRANSFORMS[round_index % len(_TRANSFORMS)]
        for base in CORE_CASES:
            if len(cases) >= target:
                break
            cases.append(replace(
                base,
                case_id=f"{base.case_id}-v{round_index + 1}",
                user_input=transform(base.user_input),
            ))
        round_index += 1
    return cases


CASES_500 = build_variant_suite(500)
CASES_1000 = build_variant_suite(1000)
