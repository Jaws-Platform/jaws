"""The foundation is planned on every pull request and applied on every release.

An `account` job reads the primary account from config/aws.yaml (`jaws config env`), and
the plan, apply and image jobs take their role, state and image repository from
its outputs, so the three can never name different accounts.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACCOUNT_ID = "${{ needs.account.outputs.account_id }}"
NAME_ROOT = "${{ needs.account.outputs.name_root }}"


def _jobs(name: str) -> dict[str, Any]:
    data: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    jobs: dict[str, Any] = data["jobs"]
    return jobs


def _step(job: dict[str, Any], predicate: Any) -> dict[str, Any]:
    matches = [s for s in job["steps"] if predicate(s)]
    assert len(matches) == 1, [s.get("name", s.get("uses")) for s in matches]
    step: dict[str, Any] = matches[0]
    return step


def _uses(action: str) -> Any:
    return lambda s: str(s.get("uses", "")).startswith(action)


def _foundation(step: dict[str, Any]) -> bool:
    """A step in foundation/, the jobs' default directory (not monitoring/'s)."""
    directory = (step.get("with") or {}).get("working-directory", step.get("working-directory"))
    return directory in (None, "foundation")


@pytest.mark.parametrize("workflow", ["ci.yml", "release-please.yml"])
def test_the_account_comes_from_the_tool(workflow: str) -> None:
    job = _jobs(workflow)["account"]
    assert job["outputs"]["account_id"] == "${{ steps.env.outputs.account_id }}"
    assert job["outputs"]["name_root"] == "${{ steps.env.outputs.name_root }}"
    step = _step(job, lambda s: s.get("id") == "env")
    # Two commands, so that a failing `jaws` fails the step instead of writing
    # nothing (a command substitution inside `echo` hides its exit code).
    assert step["run"].splitlines() == [
        "env=$(uv run jaws config env --monitoring)",
        'echo "$env" >> "$GITHUB_OUTPUT"',
    ]
    assert job["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(
    ("workflow", "job_name", "role"),
    [
        ("ci.yml", "terraform-plan", "infra-ci-plan"),
        ("release-please.yml", "apply", "infra-ci-apply"),
        ("release-please.yml", "image", "infra-ci-apply"),
        ("ci.yml", "monitoring-plan", "monitoring-ci-plan"),
        ("release-please.yml", "monitoring-apply", "monitoring-ci-apply"),
    ],
)
def test_each_job_runs_as_the_accounts_role(workflow: str, job_name: str, role: str) -> None:
    job = _jobs(workflow)[job_name]
    assert "account" in job["needs"] and "strategy" not in job
    roles = [
        s["with"]["role-to-assume"]
        for s in job["steps"]
        if _uses("aws-actions/configure-aws-credentials")(s)
    ]
    assert f"arn:aws:iam::{ACCOUNT_ID}:role/{NAME_ROOT}-" + role in roles


@pytest.mark.parametrize(
    ("workflow", "job_name"), [("ci.yml", "terraform-plan"), ("release-please.yml", "apply")]
)
def test_the_foundation_uses_the_accounts_state(workflow: str, job_name: str) -> None:
    job = _jobs(workflow)[job_name]
    init = _step(job, lambda s: _uses("./.github/actions/terraform-init")(s) and _foundation(s))
    assert init["with"]["args"] == "-backend-config=backend/prod.hcl"
    for step in job["steps"]:
        assert "-var" not in str(step.get("run", "")), "the foundation takes no account variable"


def test_the_release_applies_the_plan_it_made() -> None:
    job = _jobs("release-please.yml")["apply"]
    apply = _step(job, lambda s: "terraform apply" in str(s.get("run", "")) and _foundation(s))
    assert "databricks-credentials.sh ../config" in apply["run"]
    assert apply["run"].rstrip().endswith("tfplan")


def test_the_plan_keeps_the_name_the_ruleset_requires() -> None:
    job = _jobs("ci.yml")["terraform-plan"]
    assert job["name"] == "Terraform plan"
    comment = _step(job, _uses("marocchino/sticky-pull-request-comment"))
    assert comment["with"]["header"] == "terraform-plan"


def test_the_image_is_pushed_to_the_accounts_repository() -> None:
    job = _jobs("release-please.yml")["image"]
    assert "apply" in job["needs"]
    build = _step(job, _uses("docker/build-push-action"))
    assert build["with"]["tags"] == (
        "${{ steps.ecr.outputs.registry }}/"
        "${{ needs.account.outputs.ecr_repository }}:${{ env.TAG }}"
    )


def test_a_republished_tag_without_the_release_file_reads_the_old_config() -> None:
    """Releases cut before src/jaws/product.yaml pinned Terraform in config/terraform.yaml."""
    job = _jobs("release-please.yml")["image"]
    step = next(s for s in job["steps"] if s.get("id") == "config")
    assert "src/jaws/product.yaml" in step["run"]
    assert "config/terraform.yaml" in step["run"]
    assert "exit 1" in step["run"], "no silent empty version"
    assert "TAG" in job["env"]


def test_the_account_is_read_for_a_release_and_for_a_republished_tag() -> None:
    job = _jobs("release-please.yml")["account"]
    assert job["needs"] == "release-please"
    condition = " ".join(str(job["if"]).split())
    assert condition.startswith("!cancelled() &&"), "release-please is skipped on a dispatch"
    assert "needs.release-please.outputs.release_created == 'true'" in condition
    assert "github.event_name == 'workflow_dispatch' && inputs.tag != ''" in condition


@pytest.mark.parametrize("name", ["ci.yml", "release-please.yml", "data-access.yml"])
def test_the_tools_own_workflows_take_no_role_from_a_repository_variable(name: str) -> None:
    """(The site workflows document a site repository's own variables of these names.)"""
    text = (WORKFLOWS / name).read_text()
    assert "vars.AWS_PLAN_ROLE_ARN" not in text and "vars.AWS_APPLY_ROLE_ARN" not in text


def test_the_apply_runs_only_for_a_release() -> None:
    job = _jobs("release-please.yml")["apply"]
    assert job["if"] == (
        "github.event_name == 'push' && needs.release-please.outputs.release_created == 'true'"
    )
    assert job["environment"]["name"] == "prod"


def test_the_image_is_published_after_every_apply_or_for_a_republished_tag() -> None:
    job = _jobs("release-please.yml")["image"]
    condition = " ".join(str(job["if"]).split())
    assert condition == (
        "!cancelled() && ( (github.event_name == 'push' && needs.apply.result == 'success' && "
        "needs.release-please.outputs.release_created == 'true') || "
        "(github.event_name == 'workflow_dispatch' && inputs.tag != '') )"
    )
    assert job["environment"]["name"] == "prod"
