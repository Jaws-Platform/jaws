"""The site workflows take the platform's identity and a check-name prefix.

Without the new inputs a job runs as it did at the pins that exist today: the same
`jaws-cli` image, the role inputs, `config/` from the tool checkout, and the check names the
live sites require (`plan / jaws plan`, `preview / jaws preview deploy`).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.workflow_steps import WORKFLOWS, job

#: (workflow, job) -> (the platform-role `role`, the role input, the check name's rest)
SITE_JOBS = {
    ("site-plan.yml", "plan"): ("plan", "plan-role-arn", "plan"),
    ("site-preview.yml", "deploy"): ("preview", "preview-role-arn", "preview deploy"),
    ("site-preview.yml", "remove"): ("preview", "preview-role-arn", "preview remove"),
    ("site-deploy.yml", "deploy"): ("apply", "apply-role-arn", "release"),
}
JOBS = list(SITE_JOBS)
WORKFLOW_FILES = sorted({workflow for workflow, _ in JOBS})
IDENTITY = ("platform-image", "account-id", "name-root")
ROLE_ACTION = "./.jaws-tool/.github/actions/platform-role"
IMAGE_ACTION = "./.jaws-tool/.github/actions/platform-image"
JAWS_ACTION = "./.jaws-tool/.github/actions/jaws"
CREDENTIALS = "aws-actions/configure-aws-credentials@v6"
HAS_ROLE = "steps.role.outputs.arn != ''"


def _inputs(workflow: str) -> dict[str, Any]:
    parsed: dict[Any, Any] = yaml.safe_load((WORKFLOWS / workflow).read_text())
    found: dict[str, Any] = parsed[True]["workflow_call"]["inputs"]
    return found


def _steps(workflow: str, name: str, uses: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(workflow, name)["steps"]
    return [s for s in steps if s.get("uses") == uses]


@pytest.mark.parametrize(("workflow", "name"), JOBS)
def test_the_check_names_take_the_prefix_and_keep_today_s_by_default(
    workflow: str, name: str
) -> None:
    rest = SITE_JOBS[(workflow, name)][2]
    assert job(workflow, name)["name"] == "${{ inputs.check-prefix }} " + rest
    prefix = _inputs(workflow)["check-prefix"]
    assert prefix["default"] == "jaws"
    assert prefix["type"] == "string"


@pytest.mark.parametrize(("workflow", "name"), JOBS)
def test_a_site_job_resolves_the_platform_image_once(workflow: str, name: str) -> None:
    steps: list[dict[str, Any]] = job(workflow, name)["steps"]
    image = [i for i, s in enumerate(steps) if s.get("uses") == IMAGE_ACTION]
    assert len(image) == 1
    assert steps[image[0]]["id"] == "image"
    runs = [i for i, s in enumerate(steps) if s.get("uses") == JAWS_ACTION]
    assert runs
    assert all(image[0] < i for i in runs)
    for i in runs:
        given = steps[i]["with"]
        assert given["image"] == "${{ steps.image.outputs.image-id }}"
        assert given["platform-commit"] == "${{ steps.image.outputs.platform-commit }}"
        assert given["platform-source"] == "${{ steps.image.outputs.platform-source }}"


@pytest.mark.parametrize("workflow", WORKFLOW_FILES)
def test_each_site_workflow_takes_the_platform_s_identity(workflow: str) -> None:
    inputs = _inputs(workflow)
    for key in IDENTITY:
        assert inputs[key]["default"] == ""
        assert inputs[key]["type"] == "string"
        assert inputs[key]["required"] is False
    for wf, _name in JOBS:
        if wf == workflow:
            role_input = inputs[SITE_JOBS[(wf, _name)][1]]
            assert role_input["required"] is False
            assert role_input["default"] == ""
            assert "platform-image" in role_input["description"]


@pytest.mark.parametrize(("workflow", "name"), JOBS)
def test_in_a_hub_the_role_comes_from_the_identity(workflow: str, name: str) -> None:
    role, _role_input, _rest = SITE_JOBS[(workflow, name)]
    (role_step,) = _steps(workflow, name, ROLE_ACTION)
    assert role_step["id"] == "role"
    given = role_step["with"]
    for key in IDENTITY:
        assert given[key] == "${{ inputs." + key + " }}"
    assert given["role"] == role
    assert given["role-arn"] == "${{ inputs." + _role_input + " }}"
    (credentials,) = _steps(workflow, name, CREDENTIALS)
    assert credentials["if"] == HAS_ROLE
    assert credentials["with"]["role-to-assume"] == "${{ steps.role.outputs.arn }}"
    assert credentials["with"]["aws-region"] == "us-east-1"
    (image,) = _steps(workflow, name, IMAGE_ACTION)
    assert image["if"] == HAS_ROLE
    assert image["with"]["repository"] == "${{ inputs.platform-image }}"
    assert image["with"]["account-id"] == "${{ inputs.account-id }}"


@pytest.mark.parametrize(("workflow", "name"), JOBS)
def test_without_a_platform_image_a_site_job_runs_as_today(workflow: str, name: str) -> None:
    _role, role_input, _rest = SITE_JOBS[(workflow, name)]
    steps: list[dict[str, Any]] = job(workflow, name)["steps"]
    (role_step,) = _steps(workflow, name, ROLE_ACTION)
    condition = role_step["if"]
    for key in IDENTITY:
        assert f"inputs.{key} != ''" in condition
    fallback = "${{ steps.role.outputs.arn == '' && inputs." + role_input + " || '' }}"
    for step in _steps(workflow, name, JAWS_ACTION):
        assert step["with"]["role-arn"] == fallback
    # the role, credentials and image steps come after the tool checkout's verify step
    names = [s.get("name", "") for s in steps]
    verify = names.index("Check jaws is at this workflow's own commit")
    for step in (role_step, *_steps(workflow, name, CREDENTIALS)):
        assert steps.index(step) > verify
    for step in _steps(workflow, name, JAWS_ACTION):
        assert "image" in step["with"]


def test_the_comment_token_steps_name_the_comments_app() -> None:
    for workflow in ("site-plan.yml", "site-preview.yml"):
        text = (WORKFLOWS / workflow).read_text()
        assert "Mint a comment token for the comments App" in text
        assert "Jaws app" not in text
        assert "the platform's comments App" in _inputs(workflow)["app-client-id"]["description"]
