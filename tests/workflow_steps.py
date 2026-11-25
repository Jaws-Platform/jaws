"""Helpers to read a workflow and run one of its steps' scripts the way Actions does."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def job(workflow: str, name: str) -> dict[str, Any]:
    """The job `name` of the workflow file `workflow`."""
    parsed: dict[str, Any] = yaml.safe_load((WORKFLOWS / workflow).read_text())
    found: dict[str, Any] = parsed["jobs"][name]
    return found


def uses(job: Mapping[str, Any], action: str) -> dict[str, Any]:
    """The job's one step whose `uses` starts with `action`."""
    steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith(action)]
    assert len(steps) == 1, f"expected one {action} step, found {len(steps)}"
    found: dict[str, Any] = steps[0]
    return found


def run_step(
    workflow: str,
    job_name: str,
    step_id: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    fakes: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run step `step_id`'s script with `bash -e -c` in `cwd`; the result and GITHUB_OUTPUT."""
    step = next(s for s in job(workflow, job_name)["steps"] if s.get("id") == step_id)
    bin_dir = cwd / ".bin"
    bin_dir.mkdir(exist_ok=True)
    for name, script in (fakes or {}).items():
        fake = bin_dir / name
        fake.write_text(script)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    output = cwd / ".github_output"
    output.write_text("")
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            **env,
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
    )
    return result, output.read_text()


def hcl_values(path: Path) -> dict[str, str]:
    """A backend file's `key = "value"` lines."""
    return {
        key.strip(): value.strip().strip('"')
        for key, value in (
            line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
        )
    }


def required_checks() -> set[str]:
    """The contexts scripts/apply-repo-settings.sh requires of a pull request."""
    script = (REPO_ROOT / "scripts" / "apply-repo-settings.sh").read_text()
    return set(re.findall(r'\{ "context": "([^"]+)" \}', script))


def workflows_that_only_check(root: str) -> list[str]:
    """The sorted names of the workflows that name `root`, if none of its jobs can reach AWS.

    Fails when a job naming `root` holds `id-token`, uses `configure-aws-credentials` or
    runs `terraform plan|apply|destroy`.
    """
    names = sorted(w.name for w in WORKFLOWS.glob("*.yml") if root in w.read_text())
    for name in names:
        parsed = yaml.safe_load((WORKFLOWS / name).read_text())
        for job_name, found in parsed["jobs"].items():
            if root not in yaml.safe_dump(found):
                continue
            assert "id-token" not in found.get("permissions", {}), f"{name}: {job_name}"
            for step in found["steps"]:
                assert "configure-aws-credentials" not in step.get("uses", ""), (
                    f"{name}: {job_name}"
                )
                assert not re.search(r"terraform (plan|apply|destroy)", step.get("run", "")), (
                    f"{name}: {job_name}"
                )
    return names
