"""Every workflow builds its roles from the tool's reading of config.yaml.

No workflow reads the account or the organization itself: each role step runs
`jaws config env`, so a role ARN can never name an account the tool does not.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ROLE_WORKFLOWS = (
    "bot-apply.yml",
    "ci.yml",
    "container-release.yml",
    "data-access.yml",
    "databricks-apply.yml",
    "remote-task.yml",
)


def _workflow(name: str) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load((WORKFLOWS_DIR / name).read_text())
    return data


def _run_steps(name: str) -> Iterator[tuple[str, dict[str, Any]]]:
    for job_name, job in _workflow(name)["jobs"].items():
        for step in job.get("steps", []):
            if "run" in step:
                yield job_name, step


def _role_steps(name: str) -> list[tuple[str, dict[str, Any]]]:
    """The steps that write a role ARN for configure-aws-credentials."""
    return [(job, step) for job, step in _run_steps(name) if ":role/" in step["run"]]


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml")))
def test_no_workflow_reads_the_account_or_the_organization_itself(name: str) -> None:
    for job, step in _run_steps(name):
        for key in (".aws.account_id", ".context.organization"):
            assert key not in step["run"], f"{name} job {job}: reads {key} with yq"


@pytest.mark.parametrize("name", ROLE_WORKFLOWS)
def test_every_role_is_built_from_the_account_the_tool_resolves(name: str) -> None:
    steps = _role_steps(name)
    assert steps, f"{name} builds no role ARN: is it still a role workflow?"
    for job, step in steps:
        assert "config env" in step["run"], f"{name} job {job}: role not from `jaws config env`"
        assert step["run"].index("config env") < step["run"].index(":role/"), f"{name} job {job}"


@pytest.mark.parametrize("name", ROLE_WORKFLOWS)
def test_a_role_step_fails_when_the_tool_names_no_account(name: str) -> None:
    for job, step in _role_steps(name):
        assert "^[0-9]{12}$" in step["run"], f"{name} job {job}: account not checked"


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml")))
def test_no_workflow_addresses_an_account_of_its_own(name: str) -> None:
    """One account: no workflow takes an account input or passes `--account`."""
    workflow = _workflow(name)
    inputs = (workflow[True] or {}).get("workflow_dispatch", {}) or {}
    assert "account" not in (inputs.get("inputs") or {}), name
    for job, step in _run_steps(name):
        assert "--account" not in step["run"], f"{name} job {job}"
