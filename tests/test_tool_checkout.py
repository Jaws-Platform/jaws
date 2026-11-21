"""A consumer's pin must select the tool it runs.

A reusable workflow checks this repository out to use its action and CLI. It
must check out its own commit, the one the consumer pinned. `github.*`
describes the caller, and `github.job_workflow_sha` is empty inside a reusable
workflow: `actions/checkout` then falls back to the default branch, so every
consumer silently ran `main` (seen in jwallace145/site run 43856592781).
`job.workflow_sha` is the commit of the workflow file that defines the job.

Each checkout is followed by a step that refuses to go on unless the checkout
is at that commit. That step's script is run here, against a real repository.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
OWN_COMMIT = "${{ job.workflow_sha }}"
REPOSITORY = "Jaws-Platform/jaws"


def _jobs() -> Iterator[tuple[str, str, list[dict[str, Any]]]]:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data: dict[Any, Any] = yaml.safe_load(path.read_text())
        for job_name, job in data["jobs"].items():
            yield path.name, job_name, job.get("steps", [])


def _tool_checkouts() -> list[tuple[str, str, int, list[dict[str, Any]]]]:
    return [
        (workflow, job, index, steps)
        for workflow, job, steps in _jobs()
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout")
        and step.get("with", {}).get("repository") == REPOSITORY
    ]


def _verify_step(steps: list[dict[str, Any]], index: int) -> dict[str, Any]:
    assert index + 1 < len(steps), "the checkout is the job's last step"
    return steps[index + 1]


def test_the_reusable_workflows_check_the_tool_out() -> None:
    by_workflow = {workflow for workflow, *_ in _tool_checkouts()}
    assert {
        "site-plan.yml",
        "site-preview.yml",
        "site-deploy.yml",
        "container-release.yml",
        "remote-task.yml",
    } <= by_workflow


@pytest.mark.parametrize(
    ("workflow", "job", "index", "steps"),
    _tool_checkouts(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_every_tool_checkout_is_at_the_workflows_own_commit(
    workflow: str, job: str, index: int, steps: list[dict[str, Any]]
) -> None:
    assert steps[index]["with"]["ref"] == OWN_COMMIT, f"{workflow}:{job}"
    verify = _verify_step(steps, index)
    assert verify.get("env", {}).get("WORKFLOW_SHA") == OWN_COMMIT, f"{workflow}:{job}"
    assert verify["run"] == _the_verify_script(), f"{workflow}:{job} verifies differently"


def test_no_workflow_reads_the_empty_github_property() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert "github.job_workflow_sha" not in path.read_text(), path.name


def _the_verify_script() -> str:
    scripts = {str(_verify_step(steps, index)["run"]) for _, _, index, steps in _tool_checkouts()}
    assert len(scripts) == 1, "every workflow verifies its checkout the same way"
    return scripts.pop()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    tool = tmp_path / ".jaws-tool"
    tool.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=tool, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "x"], cwd=tool, check=True, env=env
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tool, check=True, capture_output=True, text=True
    ).stdout.strip()
    return tmp_path, head


def _verify(workspace: Path, workflow_sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _the_verify_script()],
        cwd=workspace,
        env={**os.environ, "WORKFLOW_SHA": workflow_sha},
        capture_output=True,
        text=True,
    )


def test_the_checkout_at_the_workflows_own_commit_passes(tmp_path: Path) -> None:
    workspace, head = _repository(tmp_path)
    result = _verify(workspace, head)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_empty_workflow_sha_stops_the_job(tmp_path: Path) -> None:
    workspace, _ = _repository(tmp_path)
    result = _verify(workspace, "")
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert "main" in result.stdout, "the error says what would have run instead"


def test_a_checkout_at_another_commit_stops_the_job(tmp_path: Path) -> None:
    workspace, head = _repository(tmp_path)
    other = "0" * 40 if head != "0" * 40 else "1" * 40
    result = _verify(workspace, other)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert head in result.stdout and other in result.stdout
