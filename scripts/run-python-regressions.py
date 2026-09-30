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
import re
import tempfile


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
            # The repository may live on a path where pytest's optional cache
            # is not writable (for example a sandboxed or non-ASCII drive).
            command = [
                sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                str(path),
            ]
        else:
            command = [sys.executable, str(path)]
        # Every regression file gets a fresh application data root.  Tests that
        # import config at module load must never see a developer's real
        # ~/.modagent state (or leftovers from another regression process).
        with tempfile.TemporaryDirectory(
            prefix=f"modagent-regression-{path.stem}-",
        ) as data_dir:
            test_env = child_env.copy()
            test_env["MODAGENT_DATA_DIR"] = data_dir
            try:
                result = subprocess.run(
                    command, cwd=ROOT, env=test_env, check=False, timeout=180,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                if stdout:
                    print(stdout, end="")
                if stderr:
                    print(stderr, end="", file=sys.stderr)
                print("Timed out after 180 seconds.", file=sys.stderr)
                failures.append(f"{path.name} (timeout)")
                continue
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        legacy_failure = bool(re.search(
            r"(?mi)^(?:SOME FAILED|TESTS? FAILED|FAILURES? DETECTED)\s*$",
            result.stdout or "",
        ))
        if result.returncode != 0 or legacy_failure:
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
