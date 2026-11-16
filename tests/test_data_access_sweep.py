"""scripts/data-access-sweep.sh: every sweep plans, and applies only what the plan found.

The plan, not a record in the state, decides whether the live bindings and
grants match the render: a failed or cancelled apply is retried by the next
sweep, and drift is undone. A fake `terraform` on PATH records each call and
exits as told.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "data-access-sweep.sh"

FAKE_TERRAFORM = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_CALLS"
case "$1" in
  plan) exit "${FAKE_PLAN_EXIT:-0}" ;;
  apply) exit "${FAKE_APPLY_EXIT:-0}" ;;
  *) exit 3 ;;
esac
"""


def _sweep(
    tmp_path: Path, plan_exit: int, apply_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "terraform"
    fake.write_text(FAKE_TERRAFORM)
    fake.chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    output = tmp_path / "github-output"
    output.write_text("")
    env = os.environ | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CALLS": str(calls),
        "FAKE_PLAN_EXIT": str(plan_exit),
        "FAKE_APPLY_EXIT": str(apply_exit),
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=tmp_path, check=False
    )
    return result, [line.split() for line in calls.read_text().splitlines()], output.read_text()


def test_a_plan_with_no_changes_applies_nothing(tmp_path: Path) -> None:
    result, calls, output = _sweep(tmp_path, plan_exit=0)
    assert result.returncode == 0, result.stderr
    assert [call[0] for call in calls] == ["plan"]
    assert "result=no-changes" in output


def test_a_plan_with_changes_applies_exactly_that_plan(tmp_path: Path) -> None:
    result, calls, output = _sweep(tmp_path, plan_exit=2)
    assert result.returncode == 0, result.stderr
    plan, apply = calls
    assert plan[0] == "plan" and "-detailed-exitcode" in plan and "-out=tfplan" in plan
    assert apply[0] == "apply" and apply[-1] == "tfplan"
    assert "result=applied" in output


def test_a_failed_plan_fails_the_sweep_and_applies_nothing(tmp_path: Path) -> None:
    result, calls, output = _sweep(tmp_path, plan_exit=1)
    assert result.returncode != 0
    assert [call[0] for call in calls] == ["plan"]
    assert "result=" not in output


def test_a_failed_apply_fails_the_sweep_and_records_nothing(tmp_path: Path) -> None:
    """Nothing marks the change as done: the next sweep's plan sees what is
    still live and applies it again."""
    result, calls, output = _sweep(tmp_path, plan_exit=2, apply_exit=1)
    assert result.returncode != 0
    assert [call[0] for call in calls] == ["plan", "apply"]
    assert "result=applied" not in output
