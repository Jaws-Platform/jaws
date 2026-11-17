"""Every workflow asks the tool which account a project lives in.

While projects move from the management account to production, a role ARN
built in a workflow from its own reading of config.yaml could name one account
while the tool addresses the other. So no workflow reads the account or the
organization itself: each role step runs `jaws config env`.
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
#: The workflows that apply or destroy one project's stack on request.
DISPATCHED = ("bot-apply.yml", "databricks-apply.yml")


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
def test_a_project_role_names_the_project_to_the_tool(name: str) -> None:
    """A step that puts ${PROJECT} in a role name resolves that project's
    account, not whatever project file happens to be checked out."""
    for job, step in _role_steps(name):
        if "${PROJECT}" in step["run"]:
            assert 'config env --project "$PROJECT"' in step["run"], f"{name} job {job}"


@pytest.mark.parametrize("name", ROLE_WORKFLOWS)
def test_a_role_step_fails_when_the_tool_names_no_account(name: str) -> None:
    for job, step in _role_steps(name):
        assert "^[0-9]{12}$" in step["run"], f"{name} job {job}: account not checked"


@pytest.mark.parametrize("name", DISPATCHED)
def test_a_dispatched_apply_can_choose_the_account(name: str) -> None:
    account = _workflow(name)[True]["workflow_dispatch"]["inputs"]["account"]
    assert account["type"] == "choice"
    assert account["options"] == ["", "management", "production"]
    assert account["default"] == ""
    assert account["required"] is False


@pytest.mark.parametrize("name", DISPATCHED)
def test_the_chosen_account_reaches_the_role_and_the_command(name: str) -> None:
    """The role and the stack command must address the same account."""
    job = next(iter(_workflow(name)["jobs"].values()))
    takes_account = [
        step
        for step in job["steps"]
        if "run" in step and "uv run jaws" in step["run"] and "report" not in step["run"]
    ]
    assert len(takes_account) >= 2, f"{name}: expected the role step and the stack command"
    for step in takes_account:
        assert step["env"]["ACCOUNT"] == "${{ inputs.account }}", step.get("name")
        assert '${ACCOUNT:+--account "$ACCOUNT"}' in step["run"], step.get("name")
