"""The composite action pulls the CLI image of the tool configuration's primary account.

ECR login reaches only the role's own registry, so a step checks that the role
is in the primary account (config/aws.yaml) and takes the image repository
(`ecr.repository`, config/tool.yaml) from the tool configuration at the
action's own commit. That step's script is run here, with a stand-in `aws` and
the real `yq`.

A hub's job instead passes `image`, the build it resolved and pulled with
`platform-image`, and that build's labels. The action then runs that build by its
ID with the job's own credentials: it assumes no role, logs in nowhere, reads no
`config/` and pulls nothing.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import CONFIG_DIR, REPO_ROOT, repo_config
from tests.test_github import HUB_COMMIT, HUB_SOURCE
from tests.workflow_steps import run_action_step

ACTION_DIR = REPO_ROOT / ".github" / "actions" / "jaws"
CONFIG = CONFIG_DIR
ACCOUNT = "222222222222"
#: The account the tests of the action's other steps use, the neutral one for workflow steps.
STEP_ACCOUNT = "123456789012"
REGISTRY = f"{STEP_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com"
ROLE_ARN = f"arn:aws:iam::{STEP_ACCOUNT}:role/jaws-guitar-knowledge-base-ci-plan"
#: A build of a hub's image, by the ID the runner reports.
IMAGE_ID = "sha256:" + "c" * 64
#: Stands in for docker: logs each call.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
"""


def _action() -> dict[str, Any]:
    action: dict[str, Any] = yaml.safe_load((ACTION_DIR / "action.yml").read_text())
    return action


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _action()["runs"]["steps"]
    return steps


def _step(step_id: str) -> dict[str, Any]:
    matches = [s for s in _steps() if s.get("id") == step_id]
    assert len(matches) == 1, f"the action has no single step with id {step_id}"
    return matches[0]


def _resolve(
    tmp_path: Path, account: str, config: Path
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the resolve step's script as the role of `account`; its output and GITHUB_OUTPUT."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$*" == "sts get-caller-identity --query Account --output text" ]] || '
        '{ echo "unexpected: aws $*" >&2; exit 2; }\n'
        f"echo {account}\n"
    )
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    output = tmp_path / "github_output"
    output.write_text("")
    result = subprocess.run(
        ["bash", "-e", "-c", _step("image")["run"]],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CONFIG": str(config),
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
    )
    return result, output.read_text()


def _config_without(tmp_path: Path, *path: str) -> Path:
    """A config directory with the files the step reads, one key removed."""
    raw = repo_config()
    node = raw
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    written = tmp_path / "config"
    written.mkdir()
    (written / "aws.yaml").write_text(yaml.safe_dump({"aws": raw["aws"]}))
    (written / "tool.yaml").write_text(yaml.safe_dump({"ecr": raw["ecr"]}))
    return written


def test_the_step_reads_the_config_at_the_actions_own_commit() -> None:
    env = _step("image")["env"]
    assert env["CONFIG"] == "${{ github.action_path }}/../../../config"


def test_the_image_comes_from_the_resolved_repository() -> None:
    run = next(s for s in _steps() if s.get("id") == "run")
    assert run["env"]["REPOSITORY"] == "${{ steps.image.outputs.repository }}"
    assert 'image="$REGISTRY/$REPOSITORY:$IMAGE_TAG"' in run["run"]
    assert "jaws-cli" not in (ACTION_DIR / "action.yml").read_text()


def test_the_account_pulls_its_repository(tmp_path: Path) -> None:
    result, output = _resolve(tmp_path, ACCOUNT, CONFIG)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["repository=jaws-cli"]


def test_an_account_other_than_the_primary_stops_the_job(tmp_path: Path) -> None:
    result, output = _resolve(tmp_path, "111122223333", CONFIG)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert "111122223333" in result.stdout
    assert output == ""


def test_a_config_without_an_image_repository_stops_the_job(tmp_path: Path) -> None:
    config = _config_without(tmp_path, "ecr", "repository")
    result, output = _resolve(tmp_path, ACCOUNT, config)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert output == ""


def test_the_step_reads_the_primary_account_not_another_in_the_registry(tmp_path: Path) -> None:
    """The management account is in the registry too, but jaws builds in the primary one."""
    result, output = _resolve(tmp_path, "111111111111", CONFIG)
    assert result.returncode != 0
    assert "the primary account 222222222222" in result.stdout
    assert output == ""


def run_command(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the action's `run` step for `plan` with a stand-in docker; the result and the docker
    calls. `env` overrides today's environment: no image, the registry ECR login names and
    the repository the `image` step resolved."""
    log = tmp_path / "docker.log"
    log.write_text("")
    summary = tmp_path / "summary.md"
    summary.write_text("")
    result, _ = run_action_step(
        "jaws",
        "run",
        cwd=tmp_path,
        env={
            "IMAGE": "",
            "IMAGE_TAG": _step("run")["env"]["IMAGE_TAG"],
            "REGISTRY": REGISTRY,
            "REPOSITORY": "jaws-cli",
            "COMMAND": "plan",
            "DEBUG": "false",
            "ACTIONS_STEP_DEBUG": "",
            "JAWS_PLATFORM_COMMIT": "",
            "JAWS_PLATFORM_SOURCE": "",
            "GH_TOKEN": "",
            "GITHUB_WORKSPACE": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
            "FAKE_LOG": str(log),
            **env,
        },
        fakes={"docker": FAKE_DOCKER},
    )
    return result, log.read_text().splitlines()


def test_without_an_image_the_action_runs_as_today(tmp_path: Path) -> None:
    """A project still on Jaws's own pin passes no image: the action assumes its role, logs in
    to ECR, resolves the repository from config/, pulls the versioned image and runs it."""
    assert [s.get("id") for s in _steps()] == ["check", "credentials", "ecr", "image", "run"]
    assert "if" not in _step("check")
    for step_id in ("credentials", "ecr", "image"):
        assert _step(step_id)["if"] == "inputs.image == ''", step_id
    assert "if" not in _step("run")
    credentials = _step("credentials")
    assert str(credentials["uses"]).startswith("aws-actions/configure-aws-credentials@")
    assert credentials["with"]["role-to-assume"] == "${{ inputs.role-arn }}"
    assert re.search(
        r"^ +IMAGE_TAG: v\d+\.\d+\.\d+ # x-release-please-version$",
        (ACTION_DIR / "action.yml").read_text(),
        re.MULTILINE,
    ), "the image tag is Release Please's"

    result, calls = run_command(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    image = f"{REGISTRY}/jaws-cli:{_step('run')['env']['IMAGE_TAG']}"
    assert len(calls) == 2, calls
    assert calls[0] == f"docker pull --quiet {image}"
    assert calls[1].startswith("docker run ") and calls[1].endswith(f" {image} plan")
    assert "--pull" not in calls[1], "today's run is unchanged"


@pytest.mark.parametrize(
    ("role_arn", "image", "error"),
    [
        ("", "", "::error::the jaws action needs role-arn, or an image the job already pulled"),
        (ROLE_ARN, "", None),
        ("", IMAGE_ID, None),
        ("", "some-name:latest", "::error::image "),
    ],
    ids=["neither", "a-role", "an-image", "an-image-by-name"],
)
def test_the_action_needs_a_role_or_an_image(
    tmp_path: Path, role_arn: str, image: str, error: str | None
) -> None:
    """An image is run by its ID, never by a name: Docker would fetch whatever a name
    names."""
    inputs = _action()["inputs"]
    assert inputs["role-arn"]["required"] is False and inputs["role-arn"]["default"] == ""
    assert _step("check")["env"] == {
        "ROLE_ARN": "${{ inputs.role-arn }}",
        "IMAGE": "${{ inputs.image }}",
    }
    result, output = run_action_step(
        "jaws", "check", cwd=tmp_path, env={"ROLE_ARN": role_arn, "IMAGE": image}
    )
    if error is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "::error::" not in result.stdout
    else:
        assert result.returncode != 0
        assert [line for line in result.stdout.splitlines() if line.startswith(error)], (
            result.stdout
        )
    assert output == ""


def test_a_given_image_runs_with_the_platform_s_commit(tmp_path: Path) -> None:
    """A hub's job passes the build it pulled, with the hub commit from that build's labels:
    the action runs the build by its ID, pulls nothing, and gives the CLI the commit its
    comments' footer names, and the token it reads project files with."""
    inputs = _action()["inputs"]
    for name in ("image", "platform-commit", "platform-source", "github-token"):
        assert inputs[name]["required"] is False and inputs[name]["default"] == "", name
    env = _step("run")["env"]
    assert env["IMAGE"] == "${{ inputs.image }}"
    assert env["JAWS_PLATFORM_COMMIT"] == "${{ inputs.platform-commit }}"
    assert env["JAWS_PLATFORM_SOURCE"] == "${{ inputs.platform-source }}"
    assert env["GH_TOKEN"] == "${{ inputs.github-token }}"

    result, calls = run_command(
        tmp_path,
        IMAGE=IMAGE_ID,
        REGISTRY="",
        REPOSITORY="",
        JAWS_PLATFORM_COMMIT=HUB_COMMIT,
        JAWS_PLATFORM_SOURCE=HUB_SOURCE,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1, f"one docker run and no pull: {calls}"
    run = calls[0]
    assert run.startswith("docker run ") and run.endswith(f" {IMAGE_ID} plan")
    assert " --pull never " in run, "nor an implicit one"
    for name in ("JAWS_PLATFORM_COMMIT", "JAWS_PLATFORM_SOURCE", "GH_TOKEN"):
        assert f" --env {name} " in run, name
