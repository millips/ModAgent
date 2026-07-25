"""Run legacy regression scripts in isolated Python processes.

Most files in ``tests/`` are executable assertion scripts, while newer tests
use pytest functions. Running every file in one pytest process leaks module
globals between otherwise independent regressions, so each file gets its own
interpreter here.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"


def uses_pytest_functions(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in ast.walk(tree)
    )


def main() -> int:
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    if not test_files:
        print("No regression tests found.", file=sys.stderr)
        return 1

    failures: list[str] = []
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"

    for path in test_files:
        print(f"\n=== {path.name} ===", flush=True)
        if uses_pytest_functions(path):
            command = [sys.executable, "-m", "pytest", "-q", str(path)]
        else:
            command = [sys.executable, str(path)]
        result = subprocess.run(command, cwd=ROOT, env=child_env, check=False)
        if result.returncode != 0:
            failures.append(f"{path.name} (exit {result.returncode})")

    if failures:
        print("\nRegression failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"\nAll {len(test_files)} regression files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
