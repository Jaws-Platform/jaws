"""`platform-bot-apply.yml`, `platform-databricks-apply.yml` and `platform-sweep.yml`: a hub's
by-hand applies and its data-access sweep.

Each runs the build the hub image's `current` tag names (spec 6.4), as the project's own apply
role, in the hub's `prod` environment. The steps that refuse a project or an action, and the
one that looks a project up in the build's configuration, run here as Actions runs them, with
a stand-in for `docker`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from jaws.platform import CHECK_PREFIX_WORKFLOWS, IDENTITY_WORKFLOWS
from tests.test_databricks_workflows import needs_yq
from tests.workflow_steps import WORKFLOWS, job, run_step

BOT = "platform-bot-apply.yml"
DATABRICKS = "platform-databricks-apply.yml"
SWEEP = "platform-sweep.yml"
APPLIES = [BOT, DATABRICKS]
ALL = [BOT, DATABRICKS, SWEEP]
#: Each workflow's one job.
JOB = {BOT: "apply", DATABRICKS: "apply", SWEEP: "sweep"}
TOOL = "./.jaws-tool/.github/actions"
ROLE = f"{TOOL}/platform-role"
IMAGE = f"{TOOL}/platform-image"
PROJECT_FILE = f"{TOOL}/platform-project-file"
JAWS = f"{TOOL}/jaws"
CREDENTIALS = "aws-actions/configure-aws-credentials"
IMAGE_ID = "sha256:" + "a" * 64
#: The registry as `config projects` prints it: one line of compact JSON.
REGISTRY = (
    '[{"project":"braveheart","repository":"Example-Org/braveheart","type":"bot"},'
    '{"project":"swan","repository":"Example-Org/swan","type":"bot"}]'
)
#: Stands in for docker: logs each call and answers `config projects` with FAKE_PROJECTS.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$*" in
  "run "*" config projects "*) echo "$FAKE_PROJECTS" ;;
  *) echo "unexpected: docker $*" >&2; exit 2 ;;
esac
"""


def _steps(workflow: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(workflow, JOB[workflow])["steps"]
    return steps


def _one(workflow: str, action: str) -> dict[str, Any]:
    found = [s for s in _steps(workflow) if str(s.get("uses", "")).startswith(action)]
    assert len(found) == 1, f"{workflow}: expected one {action} step, found {len(found)}"
    return found[0]


def _position(workflow: str, step_id: str) -> int:
    ids = [s.get("id") for s in _steps(workflow)]
    return ids.index(step_id)


def _inputs(path: Path) -> dict[str, Any]:
    parsed: dict[Any, Any] = yaml.safe_load(path.read_text())
    # PyYAML reads the bare `on:` key as True.
    triggers: dict[str, Any] = parsed.get("on") or parsed[True]
    found: dict[str, Any] = (triggers.get("workflow_call") or {}).get("inputs") or {}
    return found


def test_the_check_knows_every_workflow_that_takes_the_identity() -> None:
    taking = {p.name for p in WORKFLOWS.glob("*.yml") if "platform-image" in _inputs(p)}
    prefixed = {p.name for p in WORKFLOWS.glob("*.yml") if "check-prefix" in _inputs(p)}
    assert taking == set(IDENTITY_WORKFLOWS)
    assert prefixed == set(CHECK_PREFIX_WORKFLOWS)


def test_the_sweep_applies_from_main_in_prod_and_never_overlaps() -> None:
    sweep = job(SWEEP, "sweep")
    assert sweep["if"] == "github.ref == 'refs/heads/main'"
    assert sweep["environment"] == "prod"
    assert sweep["concurrency"] == {"group": "data-access-sweep", "cancel-in-progress": False}


def test_one_apply_per_project_at_a_time() -> None:
    assert job(BOT, "apply")["concurrency"] == {
        "group": "bot-apply-${{ inputs.project }}",
        "cancel-in-progress": False,
    }
    assert job(DATABRICKS, "apply")["concurrency"] == {
        "group": "databricks-apply-${{ inputs.project }}",
        "cancel-in-progress": False,
    }


@pytest.mark.parametrize("workflow", ALL)
def test_each_job_runs_in_prod_with_the_identity(workflow: str) -> None:
    assert job(workflow, JOB[workflow])["environment"] == "prod"
    inputs = _inputs(WORKFLOWS / workflow)
    for name in ("platform-image", "account-id", "name-root"):
        assert inputs[name]["required"] is True
    assert _one(workflow, IMAGE)["with"] == {
        "account-id": "${{ inputs.account-id }}",
        "repository": "${{ inputs.platform-image }}",
    }


@pytest.mark.parametrize("workflow", ALL)
def test_the_by_hand_applies_and_the_sweep_run_the_current_build(workflow: str) -> None:
    pulled = _one(workflow, IMAGE)["with"]
    assert "digest" not in pulled
    assert "artifact" not in pulled
    assert "tag" not in pulled


@pytest.mark.parametrize("workflow", ALL)
def test_the_project_file_reads_carry_a_token(workflow: str) -> None:
    ran = [s for s in _steps(workflow) if str(s.get("uses", "")).startswith(JAWS)]
    assert len(ran) == 1
    assert ran[0]["with"]["github-token"] == "${{ github.token }}"
    assert ran[0]["with"]["image"] == "${{ steps.image.outputs.image-id }}"
    assert ran[0]["with"]["platform-commit"] == "${{ steps.image.outputs.platform-commit }}"
    assert ran[0]["with"]["platform-source"] == "${{ steps.image.outputs.platform-source }}"


@pytest.mark.parametrize("workflow", APPLIES)
def test_a_project_is_applied_with_its_apply_role(workflow: str) -> None:
    role = _one(workflow, ROLE)["with"]
    assert role["role"] == "apply"
    assert role["project"] == "${{ inputs.project }}"


def test_the_sweep_applies_with_the_data_access_role() -> None:
    role = _one(SWEEP, ROLE)["with"]
    assert (role["role"], role["project"]) == ("apply", "data-access")
    ran = _one(SWEEP, JAWS)["with"]
    assert ran["command"] == "platform apply data-access"


@pytest.mark.parametrize("workflow", ALL)
def test_every_run_reaches_the_shell_through_env(workflow: str) -> None:
    for step in _steps(workflow):
        assert "${{" not in step.get("run", ""), f"{workflow}: {step.get('name')}"


@pytest.mark.parametrize("workflow", APPLIES)
@pytest.mark.parametrize("own", ["infra", "monitoring", "data-access"])
def test_the_platform_s_own_stacks_are_refused_before_any_role(
    workflow: str, own: str, tmp_path: Path
) -> None:
    result, _ = run_step(workflow, "apply", "project", cwd=tmp_path, env={"PROJECT": own})
    assert result.returncode == 1
    assert f"{own} is one of the platform's own stacks, not a" in result.stdout
    assert _position(workflow, "project") < _steps(workflow).index(_one(workflow, ROLE))


@pytest.mark.parametrize("workflow", APPLIES)
def test_a_project_is_let_through_to_its_role(workflow: str, tmp_path: Path) -> None:
    result, _ = run_step(workflow, "apply", "project", cwd=tmp_path, env={"PROJECT": "braveheart"})
    assert result.returncode == 0, result.stderr


def test_the_refusals_name_the_kind_of_project() -> None:
    bot = next(s for s in _steps(BOT) if s.get("id") == "project")["run"]
    databricks = next(s for s in _steps(DATABRICKS) if s.get("id") == "project")["run"]
    assert "not a bot or research project" in bot
    assert "not a Databricks project" in databricks


def _lookup(
    workflow: str, project: str, tmp_path: Path, registry: str = REGISTRY
) -> tuple[Any, str, list[str]]:
    log = tmp_path / "docker.log"
    log.write_text("")
    result, output = run_step(
        workflow,
        "apply",
        "lookup",
        cwd=tmp_path,
        env={
            "IMAGE_ID": IMAGE_ID,
            "PROJECT": project,
            "FAKE_LOG": str(log),
            "FAKE_PROJECTS": registry,
        },
        fakes={"docker": FAKE_DOCKER},
    )
    return result, output, log.read_text().splitlines()


@needs_yq
@pytest.mark.parametrize(
    ("workflow", "types", "label"),
    [
        (BOT, "bot research", "a bot or research project"),
        (DATABRICKS, "databricks", "a Databricks project"),
    ],
)
def test_a_project_that_is_not_a_bot_is_refused(
    workflow: str, types: str, label: str, tmp_path: Path
) -> None:
    result, output, calls = _lookup(workflow, "lighthouse", tmp_path)
    assert result.returncode == 1
    assert f"lighthouse is not {label} in the platform's configuration" in result.stdout
    assert output == ""
    # Offline, inside the build, and for the types that apply asks for.
    assert calls == [
        f"docker run --rm --network none --pull never {IMAGE_ID} config projects {types}"
    ]


@needs_yq
@pytest.mark.parametrize("workflow", APPLIES)
def test_a_registered_project_is_looked_up_to_its_repository(workflow: str, tmp_path: Path) -> None:
    result, output, _ = _lookup(workflow, "swan", tmp_path)
    assert result.returncode == 0, result.stderr
    assert output == "repository=Example-Org/swan\n"


@pytest.mark.parametrize("workflow", APPLIES)
def test_the_project_file_must_name_the_project(workflow: str) -> None:
    steps = _steps(workflow)
    step = _one(workflow, PROJECT_FILE)
    assert step["with"]["on-mismatch"] == "refuse"
    assert step["with"]["project"] == "${{ inputs.project }}"
    assert step["with"]["repository"] == "${{ steps.lookup.outputs.repository }}"
    assert _position(workflow, "lookup") < steps.index(step) < steps.index(_one(workflow, JAWS))
    if workflow == BOT:
        assert step["with"]["ref"] == "${{ inputs.consumer-ref }}"
    else:
        assert "ref" not in step["with"]
        assert "consumer-ref" not in _inputs(WORKFLOWS / workflow)


def test_the_commands_are_today_s() -> None:
    bot = _one(BOT, JAWS)["with"]["command"]
    assert bot == "--file .consumer/jaws.yaml ${{ inputs.destroy && 'destroy --yes' || 'apply' }}"
    databricks = _one(DATABRICKS, JAWS)["with"]["command"]
    assert databricks == (
        "--file .consumer/jaws.yaml ${{ inputs.action == 'destroy' && 'destroy --yes' || "
        "inputs.action == 'doctor' && 'databricks doctor' || 'apply' }}"
    )
    inputs = _inputs(WORKFLOWS / BOT)
    assert (inputs["destroy"]["type"], inputs["destroy"]["default"]) == ("boolean", False)
    assert inputs["consumer-ref"]["default"] == ""
    action = _inputs(WORKFLOWS / DATABRICKS)["action"]
    assert (action["type"], action["default"]) == ("string", "apply")


@pytest.mark.parametrize("action", ["apply", "destroy", "doctor"])
def test_a_databricks_action_is_one_of_three(action: str, tmp_path: Path) -> None:
    result, _ = run_step(DATABRICKS, "apply", "action", cwd=tmp_path, env={"ACTION": action})
    assert result.returncode == 0, result.stdout


def test_any_other_databricks_action_stops(tmp_path: Path) -> None:
    result, _ = run_step(DATABRICKS, "apply", "action", cwd=tmp_path, env={"ACTION": "deploy"})
    assert result.returncode == 1
    assert "action must be apply, destroy or doctor, got 'deploy'" in result.stdout


@pytest.mark.parametrize("workflow", ALL)
def test_each_job_runs_the_tool_from_its_own_commit(workflow: str) -> None:
    steps = _steps(workflow)
    checkout = next(s for s in steps if s.get("with", {}).get("repository") == "Jaws-Platform/jaws")
    assert checkout["with"]["ref"] == "${{ job.workflow_sha }}"
    assert checkout["with"]["path"] == ".jaws-tool"
    assert steps.index(checkout) < steps.index(_one(workflow, ROLE))
    assert steps.index(_one(workflow, ROLE)) < steps.index(_one(workflow, CREDENTIALS))
    assert steps.index(_one(workflow, CREDENTIALS)) < steps.index(_one(workflow, IMAGE))
    assert steps.index(_one(workflow, IMAGE)) < steps.index(_one(workflow, JAWS))
