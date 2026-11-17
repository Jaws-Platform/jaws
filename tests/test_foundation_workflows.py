"""The foundation is planned on every pull request and applied on every release,
once per bootstrapped account.

The tool lists the accounts (`jaws config accounts`: management always,
production once `production.bootstrapped` is true), and each job runs as a
matrix over that list. A leg takes its role, its state and its `-var account`
from its own matrix entry, so the three can never name different accounts.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from jaws.settings import load_settings
from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MATRIX = "${{ fromJSON(needs.accounts.outputs.accounts) }}"
NOT_MANAGEMENT = "matrix.account != 'management'"


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


@pytest.mark.parametrize("workflow", ["ci.yml", "release-please.yml"])
def test_the_tool_lists_the_accounts(workflow: str) -> None:
    job = _jobs(workflow)["accounts"]
    assert job["outputs"] == {"accounts": "${{ steps.list.outputs.accounts }}"}
    step = _step(job, lambda s: s.get("id") == "list")
    # Two commands, so that a failing `jaws` fails the step instead of writing
    # an empty list (a command substitution inside `echo` hides its exit code).
    assert step["run"].splitlines() == [
        "accounts=$(uv run jaws config accounts)",
        'echo "accounts=$accounts" >> "$GITHUB_OUTPUT"',
    ]
    assert job["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(
    ("workflow", "job_name", "role"),
    [
        ("ci.yml", "terraform-plan", "infra-ci-plan"),
        ("release-please.yml", "apply", "infra-ci-apply"),
        ("release-please.yml", "image", "infra-ci-apply"),
    ],
)
def test_each_leg_runs_as_its_own_accounts_role(workflow: str, job_name: str, role: str) -> None:
    job = _jobs(workflow)[job_name]
    assert "accounts" in job["needs"]
    assert job["strategy"] == {"fail-fast": False, "matrix": {"include": MATRIX}}
    credentials = _step(job, _uses("aws-actions/configure-aws-credentials"))
    assert credentials["with"]["role-to-assume"] == (
        "arn:aws:iam::${{ matrix.account_id }}:role/${{ matrix.organization }}-" + role
    )


@pytest.mark.parametrize(
    ("workflow", "job_name"), [("ci.yml", "terraform-plan"), ("release-please.yml", "apply")]
)
def test_each_leg_uses_its_own_accounts_state_and_configuration(
    workflow: str, job_name: str
) -> None:
    job = _jobs(workflow)[job_name]
    init = _step(job, _uses("./.github/actions/terraform-init"))
    assert init["with"]["args"] == "-backend-config=backend/${{ matrix.account }}.hcl"
    plan = _step(job, lambda s: "terraform plan" in str(s.get("run", "")))
    assert plan["env"]["ACCOUNT"] == "${{ matrix.account }}"
    assert '-var "account=$ACCOUNT"' in plan["run"]
    assert 'databricks-credentials.sh ../config.yaml "$ACCOUNT"' in plan["run"]


def test_the_release_applies_the_plan_it_made_with_that_accounts_credential() -> None:
    job = _jobs("release-please.yml")["apply"]
    apply = _step(job, lambda s: "terraform apply" in str(s.get("run", "")))
    assert apply["env"]["ACCOUNT"] == "${{ matrix.account }}"
    assert 'databricks-credentials.sh ../config.yaml "$ACCOUNT"' in apply["run"]
    # A saved plan carries its variables: applying it cannot address another account.
    assert apply["run"].rstrip().endswith("tfplan")
    assert "-var" not in apply["run"]


def test_the_management_plan_keeps_the_name_the_ruleset_requires() -> None:
    job = _jobs("ci.yml")["terraform-plan"]
    assert job["name"] == (
        "Terraform plan${{ " + NOT_MANAGEMENT + " && format(' ({0})', matrix.account) || '' }}"
    )


def test_each_accounts_plan_has_its_own_sticky_comment() -> None:
    job = _jobs("ci.yml")["terraform-plan"]
    comment = _step(job, _uses("marocchino/sticky-pull-request-comment"))
    assert comment["with"]["header"] == (
        "terraform-plan${{ " + NOT_MANAGEMENT + " && format('-{0}', matrix.account) || '' }}"
    )
    build = _step(job, lambda s: "report plan-comment" in str(s.get("run", "")))
    assert build["env"]["ACCOUNT"] == "${{ matrix.account }}"
    assert '--subject "jwall-engineering-infra/foundation${SUFFIX}"' in build["run"]


def test_the_image_is_pushed_to_each_accounts_repository() -> None:
    job = _jobs("release-please.yml")["image"]
    assert "apply" in job["needs"]
    build = _step(job, _uses("docker/build-push-action"))
    assert build["with"]["tags"] == (
        "${{ steps.ecr.outputs.registry }}/${{ matrix.ecr_repository }}:${{ env.TAG }}"
    )
    for step in job["steps"]:
        assert ".ecr.repository" not in str(step.get("run", "")), "the repository is the matrix's"


def test_the_accounts_are_listed_for_a_release_and_for_a_republished_tag() -> None:
    job = _jobs("release-please.yml")["accounts"]
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


@pytest.mark.parametrize("account", ["management", "production"])
def test_each_account_has_a_backend_file_for_its_own_state_bucket(account: str) -> None:
    """`-backend-config=backend/<account>.hcl` must point at the bucket the tool
    names for that account, or a leg would keep its state in the other's."""
    settings = load_settings(REPO_ROOT / "config.yaml", environ={}, account=account)  # type: ignore[arg-type]
    backend = (REPO_ROOT / "foundation" / "backend" / f"{account}.hcl").read_text()
    values = dict(
        (key.strip(), value.strip().strip('"'))
        for key, value in (line.split("=", 1) for line in backend.splitlines() if "=" in line)
    )
    assert values["bucket"] == settings.state.bucket
    assert values["region"] == settings.state.region
    assert values["key"] == "project=infra/env=prod/infra-prod.tfstate"


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
