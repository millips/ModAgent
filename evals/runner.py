from __future__ import annotations

import argparse
import json
from collections import Counter

from modagent.orchestration.models import TaskSpec
from modagent.orchestration.policies import allowed_tools
from modagent.orchestration.router import route_message

from .core_cases import CORE_CASES
from .variants import CASES_500, CASES_1000


def run_deterministic(cases=None) -> dict:
    cases = list(cases or CORE_CASES)
    failures = []
    for case in cases:
        route = route_message(
            case.user_input,
            selection_action=case.selection_action,
            has_selection=case.has_selection,
            regenerate=case.regenerate,
        )
        spec = TaskSpec.create(
            session_id="eval", game_id="eval-game", intent=route.intent,
            user_goal=case.user_input,
            authorization={
                "install": route.install_authorized,
                "destructive": route.destructive_authorized,
            },
        )
        permitted = allowed_tools(spec)
        errors = []
        if route.intent != case.expected_intent:
            errors.append(f"intent={route.intent.value}")
        forbidden = sorted(set(case.must_not_use).intersection(permitted))
        if forbidden:
            errors.append("forbidden_tools=" + ",".join(forbidden))
        if errors:
            failures.append({"case_id": case.case_id, "errors": errors})
    return {
        "total": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "pass_rate": round((len(cases) - len(failures)) / len(cases), 4),
        "categories": dict(Counter(case.category for case in cases)),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent Core v2 golden cases")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--suite", choices=("120", "500", "1000"), default="120")
    args = parser.parse_args()
    suites = {"120": CORE_CASES, "500": CASES_500, "1000": CASES_1000}
    report = run_deterministic(suites[args.suite])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Agent Core v2: {report['passed']}/{report['total']} passed")
        for failure in report["failures"]:
            print(f"FAIL {failure['case_id']}: {'; '.join(failure['errors'])}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
