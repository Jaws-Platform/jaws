"""The reusable remote-task workflow: who may run it and how it cleans up."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tests.conftest import REPO_ROOT
from tests.test_databricks_workflows import needs_yq
from tests.workflow_steps import run_step

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "remote-task.yml"


def _workflow() -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return data


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _workflow()["jobs"]["task"]["steps"]
    return steps


def _index(predicate: Any) -> int:
    return next(i for i, s in enumerate(_steps()) if predicate(s))


def test_it_is_reusable_with_the_planned_inputs() -> None:
    call = _workflow()[True]["workflow_call"]
    assert set(call["inputs"]) == {
        "project", "script", "args", "profile", "instance-type", "market", "max-hours",
        "task-id", "artifact", "artifact-path", "debug", "campaign",
        "platform-image", "account-id", "name-root",
    }  # fmt: skip
    assert call["inputs"]["project"]["required"] and call["inputs"]["script"]["required"]
    assert call["inputs"]["args"]["default"] == "[]"
    assert call["inputs"]["profile"]["default"] == "cpu"
    assert call["inputs"]["artifact-path"]["default"] == "out"


def test_permissions_and_timeout() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["task"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["timeout-minutes"] == 360  # GitHub-hosted jobs stop at six hours


def test_the_first_step_refuses_forks_and_other_events() -> None:
    first = _steps()[0]
    script = first["run"]
    assert "fork pull requests cannot use the standardized task runners" in script
    assert "github.event.pull_request.head.repo.full_name" in str(first["env"])
    # ref:refs/heads/main is also the subject of pull_request_target, issue_comment
    # and workflow_run runs on main, which can carry fork code: refuse them here.
    assert re.search(r"push\|workflow_dispatch\|schedule\)", script)
    assert "pull_request)" in script and "*)" in script
    credentials = _index(lambda s: "configure-aws-credentials" in s.get("uses", ""))
    assert credentials > 0


def test_the_role_is_built_from_config_with_a_long_enough_session() -> None:
    role = _steps()[_index(lambda s: s.get("id") == "role")]
    assert 'jaws --config "$JAWS_TOOL_CONFIG" config env' in role["run"]
    assert '-${PROJECT}-ci-task"' in role["run"]
    assert "3600" in role["run"]
    creds = _steps()[_index(lambda s: "configure-aws-credentials" in s.get("uses", ""))]
    assert creds["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    assert creds["with"]["role-duration-seconds"] == "${{ steps.role.outputs.duration }}"


def test_the_task_step_runs_the_pr_head_and_gets_no_github_token() -> None:
    step = _steps()[_index(lambda s: s.get("name") == "jaws task run")]
    assert "GITHUB_TOKEN" not in str(step.get("env", {}))
    assert step["env"]["REF"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert '--run-id "$RUN_ID"' in step["run"] and '--task-id "$TASK_ID"' in step["run"]
    assert '-- "${argv[@]}"' in step["run"]
    # GitHub signals the step's own process on cancel: exec the CLI so that is
    # the CLI itself, not bash or uv, and its handlers terminate the instance.
    assert "exec .jaws-tool/.venv/bin/jaws" in step["run"]
    env = _workflow()["jobs"]["task"]["env"]
    assert env["RUN_ID"] == "${{ github.run_id }}-${{ github.run_attempt }}"
    # Matrix legs already need distinct artifact names: they name the task too.
    assert env["TASK_ID"] == "${{ inputs.task-id || inputs.artifact }}"
    assert _workflow()[True]["workflow_call"]["inputs"]["task-id"]["default"] == ""


def test_no_step_hands_out_the_github_token() -> None:
    assert "github.token" not in WORKFLOW.read_text()
    assert "secrets." not in WORKFLOW.read_text()
    for step in _steps():
        if step.get("uses", "").startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False


def test_upload_and_cleanup_always_run() -> None:
    upload = _steps()[_index(lambda s: s.get("name") == "Upload the task's outputs")]
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "${{ inputs.artifact-path }}"
    cleanup = _steps()[-1]
    assert cleanup["if"].startswith("always()")
    assert 'task terminate --run-id "$RUN_ID" --task-id "$TASK_ID"' in cleanup["run"]


def test_runs_the_cli_from_this_workflow_commit() -> None:
    text = WORKFLOW.read_text()
    assert "ref: ${{ job.workflow_sha }}" in text
    assert '--config "$JAWS_TOOL_CONFIG"' in text
    assert "--config .jaws-tool/config" not in text
    env = _workflow()["jobs"]["task"]["env"]
    assert env["JAWS_TOOL_CONFIG"] == (
        "${{ inputs.platform-image != '' && '.jaws-platform/config' || '.jaws-tool/config' }}"
    )
    assert "CLI" not in env


def test_outcome_and_interruption_are_outputs() -> None:
    workflow = _workflow()
    outputs = workflow[True]["workflow_call"]["outputs"]
    assert outputs["outcome"]["value"] == "${{ jobs.task.outputs.outcome }}"
    assert outputs["interrupted-at"]["value"] == "${{ jobs.task.outputs.interrupted-at }}"
    job = workflow["jobs"]["task"]
    assert job["outputs"] == {
        "outcome": "${{ steps.task.outputs.outcome }}",
        "interrupted-at": "${{ steps.task.outputs.interrupted-at }}",
    }
    assert _steps()[_index(lambda s: s.get("id") == "task")]["name"] == "jaws task run"


def test_the_outcome_description_lists_no_price() -> None:
    outputs = _workflow()[True]["workflow_call"]["outputs"]
    assert "no-price" in outputs["outcome"]["description"]


def test_an_interrupted_tasks_artifact_says_so() -> None:
    upload = _steps()[_index(lambda s: s.get("name") == "Upload the task's outputs")]
    suffix = "${{ steps.task.outputs.outcome == 'interrupted' && '-interrupted' || '' }}"
    assert upload["with"]["name"] == "${{ inputs.artifact }}" + suffix


def test_the_task_step_passes_the_market_and_the_pull_request() -> None:
    step = _steps()[_index(lambda s: s.get("id") == "task")]
    assert step["env"]["MARKET"] == "${{ inputs.market }}"
    assert step["env"]["PULL_REQUEST"] == "${{ github.event.pull_request.number }}"
    assert 'flags+=(--market "$MARKET")' in step["run"]
    assert 'flags+=(--pull-request "$PULL_REQUEST")' in step["run"]


def test_the_task_step_passes_a_campaign_only_when_named() -> None:
    """No campaign input, no --campaign: such a run carries no Campaign tag."""
    inputs = _workflow()[True]["workflow_call"]["inputs"]
    assert inputs["campaign"]["default"] == "" and inputs["campaign"]["type"] == "string"
    step = _steps()[_index(lambda s: s.get("id") == "task")]
    assert step["env"]["CAMPAIGN"] == "${{ inputs.campaign }}"
    assert 'if [ -n "$CAMPAIGN" ]; then flags+=(--campaign "$CAMPAIGN"); fi' in step["run"]
    assert "inputs.campaign" not in str(step["run"])  # through the environment, never inlined


IDENTITY_IF = "inputs.platform-image != '' || inputs.account-id != '' || inputs.name-root != ''"
FIXTURE = "account_id=222222222222\nname_root=jaws\n"


def test_the_cleanup_terminates_with_the_job_s_configuration(tmp_path: Path) -> None:
    """A job's env can't read env, so the cleanup spells the quoted config itself."""
    cleanup = _steps()[_index(lambda s: s.get("id") == "terminate")]
    assert cleanup["if"].startswith("always()")
    jaws = tmp_path / ".jaws-tool" / ".venv" / "bin" / "jaws"
    jaws.parent.mkdir(parents=True)
    jaws.write_text('#!/bin/bash\necho "$@" > args.log\n')
    jaws.chmod(0o755)
    result, _ = run_step(
        "remote-task.yml",
        "task",
        "terminate",
        cwd=tmp_path,
        env={"JAWS_TOOL_CONFIG": ".jaws-platform/config", "RUN_ID": "1-1", "TASK_ID": "t"},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "args.log").read_text().strip() == (
        "--config .jaws-platform/config task terminate --run-id 1-1 --task-id t"
    )


def test_in_a_hub_the_task_role_comes_from_the_platform_s_identity() -> None:
    steps = _steps()
    platform = steps[_index(lambda s: s.get("id") == "platform")]
    assert platform["if"] == IDENTITY_IF
    assert platform["uses"] == "./.jaws-tool/.github/actions/platform-role"
    assert platform["with"] == {
        "platform-image": "${{ inputs.platform-image }}",
        "account-id": "${{ inputs.account-id }}",
        "name-root": "${{ inputs.name-root }}",
        "role": "task",
        "project": "${{ inputs.project }}",
    }
    role = steps[_index(lambda s: s.get("id") == "role")]
    assert role["env"]["PLATFORM_ARN"] == "${{ steps.platform.outputs.arn }}"
    assert 'if [ -n "$PLATFORM_ARN" ]' in role["run"]
    assert role["run"].count("--config") == 1
    assert _index(lambda s: s.get("id") == "platform") < _index(lambda s: s.get("id") == "role")
    creds = steps[_index(lambda s: "configure-aws-credentials" in s.get("uses", ""))]
    assert creds["with"]["role-duration-seconds"] == "${{ steps.role.outputs.duration }}"


def test_in_a_hub_the_cli_reads_the_platform_image_s_configuration() -> None:
    steps = _steps()
    credentials = _index(lambda s: "configure-aws-credentials" in s.get("uses", ""))
    image = _index(lambda s: s.get("id") == "image")
    task = _index(lambda s: s.get("id") == "task")
    assert credentials < image < task
    assert steps[image]["if"] == "steps.platform.outputs.arn != ''"
    assert steps[image]["uses"] == "./.jaws-tool/.github/actions/platform-image"
    assert steps[image]["with"]["extract"] == ".jaws-platform"
    assert steps[task]["env"]["JAWS_INFRA_ROOT"] == "${{ steps.image.outputs.infra-root }}"
    assert steps[task]["env"]["JAWS_PLATFORM_COMMIT"] == (
        "${{ steps.image.outputs.platform-commit }}"
    )
    assert steps[task]["env"]["JAWS_PLATFORM_SOURCE"] == (
        "${{ steps.image.outputs.platform-source }}"
    )


@needs_yq
def test_without_a_platform_image_a_task_runs_as_today(tmp_path: Path) -> None:
    fake_uv = (
        "#!/bin/bash\n"
        '[ "$1 $2 $3 $4 $5 $6" = "run --no-dev --project .jaws-tool jaws --config" ] || exit 9\n'
        '[ "$8" = config ] && [ "$9" = env ] || exit 9\n'
        f"printf '{FIXTURE}'\n"
    )
    result, output = run_step(
        "remote-task.yml",
        "task",
        "role",
        cwd=tmp_path,
        env={
            "PLATFORM_ARN": "",
            "PROJECT": "braveheart",
            "PROFILE": "cpu",
            "MAX_HOURS": "1",
            "JAWS_TOOL_CONFIG": ".jaws-tool/config",
        },
        fakes={"uv": fake_uv},
    )
    assert result.returncode == 0, result.stderr
    assert "arn=arn:aws:iam::222222222222:role/jaws-braveheart-ci-task\n" in output
    assert "duration=7200\n" in output


def test_in_a_hub_the_role_step_does_not_read_the_configuration(tmp_path: Path) -> None:
    arn = "arn:aws:iam::123456789012:role/jaws-braveheart-ci-task"
    result, output = run_step(
        "remote-task.yml",
        "task",
        "role",
        cwd=tmp_path,
        env={
            "PLATFORM_ARN": arn,
            "PROJECT": "braveheart",
            "PROFILE": "cpu",
            "MAX_HOURS": "1",
            "JAWS_TOOL_CONFIG": ".jaws-platform/config",
        },
        fakes={"uv": "#!/bin/bash\nexit 9\n"},
    )
    assert result.returncode == 0, result.stderr
    assert f"arn={arn}\n" in output and "duration=7200\n" in output
