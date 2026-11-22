"""The monitoring stack is planned on pull requests and applied only on release.

Merging a pull request provisions nothing: CI validates, tests and plans
monitoring/ (with jaws-monitoring-ci-plan) and never applies it; the Release
monitoring-apply job applies it after the foundation's apply job (with
jaws-monitoring-ci-apply), so one release creates the stack's roles and billing
bucket, then the stack, and a failed monitoring apply never holds back the CLI
image. Until the release that creates the plan role, the pull request plan is
skipped with a notice instead of failing.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACCOUNT_ID = "${{ needs.account.outputs.account_id }}"
NAME_ROOT = "${{ needs.account.outputs.name_root }}"
CONFIGURED = "needs.account.outputs.monitoring == 'configured'"


def _jobs(name: str) -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]
    return jobs


def _uses(step: dict[str, Any], action: str) -> bool:
    return str(step.get("uses", "")).startswith(action)


def _in_monitoring(step: dict[str, Any], job: dict[str, Any] | None = None) -> bool:
    """A step in monitoring/: its own working directory, or, for a `run` step
    that names none, its job's default."""
    directory = (step.get("with") or {}).get("working-directory", step.get("working-directory"))
    if directory is None and "run" in step and job is not None:
        directory = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
    return bool(directory == "monitoring")


def test_the_account_job_says_whether_monitoring_is_configured() -> None:
    for name in ("ci.yml", "release-please.yml"):
        job = _jobs(name)["account"]
        assert job["outputs"]["monitoring"] == "${{ steps.env.outputs.monitoring }}", name
        env = next(s for s in job["steps"] if s.get("id") == "env")
        assert "jaws config env --monitoring" in env["run"], name


def test_ci_validates_tests_and_lints_both_roots_without_credentials() -> None:
    jobs = _jobs("ci.yml")
    for root in ("monitoring", "billing-export"):
        job = jobs[f"{root}-stack"]
        assert job["defaults"]["run"]["working-directory"] == root
        assert job["permissions"] == {"contents": "read"}
        init = next(s for s in job["steps"] if _uses(s, "./.github/actions/terraform-init"))
        assert init["with"] == {"args": "-backend=false", "working-directory": root}
        runs = [str(s.get("run", "")) for s in job["steps"]]
        assert any("terraform validate" in r for r in runs), root
        assert any("terraform test" in r for r in runs), root
        assert any("tflint --config" in r for r in runs), root
        for step in job["steps"]:
            assert not _uses(step, "aws-actions/configure-aws-credentials"), root
            assert not re.search(r"terraform (plan|apply|destroy)", str(step.get("run", ""))), root


def test_pull_requests_plan_monitoring_with_its_plan_role() -> None:
    job = _jobs("ci.yml")["monitoring-plan"]
    assert "account" in job["needs"] and "monitoring-stack" in job["needs"]
    condition = " ".join(str(job["if"]).split())
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert CONFIGURED in condition
    assert job["permissions"]["id-token"] == "write"
    assert job["defaults"]["run"]["working-directory"] == "monitoring"
    credentials = next(s for s in job["steps"] if _uses(s, "aws-actions/configure-aws-credentials"))
    assert credentials["with"]["role-to-assume"] == (
        f"arn:aws:iam::{ACCOUNT_ID}:role/{NAME_ROOT}-monitoring-ci-plan"
    )
    init = next(s for s in job["steps"] if _uses(s, "./.github/actions/terraform-init"))
    assert init["with"] == {
        "args": "-backend-config=backend/prod.hcl",
        "working-directory": "monitoring",
    }
    plan = next(s for s in job["steps"] if "terraform plan" in str(s.get("run", "")))
    assert "-out=tfplan" in plan["run"]


def test_the_plan_is_skipped_with_a_notice_until_its_role_exists() -> None:
    """The first release's foundation apply creates the role: a pull request
    planned before it must not fail."""
    steps = _jobs("ci.yml")["monitoring-plan"]["steps"]
    credentials = next(s for s in steps if _uses(s, "aws-actions/configure-aws-credentials"))
    assert credentials["id"] == "assume"
    assert credentials["continue-on-error"] is True
    skip = next(s for s in steps if "Skip" in str(s.get("name", "")))
    assert skip["if"] == "steps.assume.outcome != 'success'"
    assert "::notice::" in skip["run"] and "GITHUB_STEP_SUMMARY" in skip["run"]
    terraform = [s for s in steps if "terraform" in str(s.get("run", "")) + str(s.get("uses", ""))]
    terraform = [s for s in terraform if not _uses(s, "hashicorp/setup-terraform")]
    assert terraform
    for step in terraform:
        assert "steps.assume.outcome == 'success'" in str(step.get("if", "")), step


def test_merging_a_pull_request_provisions_nothing() -> None:
    """Only the Release monitoring-apply job applies monitoring/."""
    appliers = [
        (path.name, name)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
        for step in job.get("steps", [])
        if _in_monitoring(step, job) and "terraform apply" in str(step.get("run", ""))
    ]
    assert appliers == [("release-please.yml", "monitoring-apply")]
    assert "terraform apply" not in (WORKFLOWS / "ci.yml").read_text()


def test_the_release_applies_monitoring_after_the_foundation() -> None:
    """In a job of its own: it needs the foundation's apply, which creates the
    stack's roles and state prefix, and the CLI image does not need it, so a
    failed monitoring apply never holds back the image."""
    jobs = _jobs("release-please.yml")
    job = jobs["monitoring-apply"]
    assert job["needs"] == ["release-please", "account", "apply"]
    assert " ".join(str(job["if"]).split()) == (
        "github.event_name == 'push' && "
        f"needs.release-please.outputs.release_created == 'true' && {CONFIGURED}"
    )
    assert job["environment"]["name"] == "prod"  # the apply role trusts only prod
    assert job["permissions"] == {"id-token": "write", "contents": "read"}
    checkout = next(s for s in job["steps"] if _uses(s, "actions/checkout"))
    assert checkout == next(s for s in jobs["apply"]["steps"] if _uses(s, "actions/checkout"))
    assert checkout["with"]["ref"] == "${{ needs.release-please.outputs.tag_name }}"

    image = jobs["image"]
    assert image["needs"] == ["release-please", "account", "apply"]
    assert "monitoring-apply" not in str(image["if"])

    # The foundation's apply job touches nothing of the stack.
    for step in jobs["apply"]["steps"]:
        assert not _in_monitoring(step, jobs["apply"]), step
        assert "monitoring" not in str((step.get("with") or {}).get("role-to-assume", "")), step


def test_the_monitoring_apply_job_applies_the_plan_it_made_with_its_role() -> None:
    job = _jobs("release-please.yml")["monitoring-apply"]
    steps = job["steps"]

    def index(predicate: Any) -> int:
        matches = [i for i, s in enumerate(steps) if predicate(s)]
        assert len(matches) == 1, matches
        return matches[0]

    credentials = index(lambda s: _uses(s, "aws-actions/configure-aws-credentials"))
    init = index(lambda s: _uses(s, "./.github/actions/terraform-init") and _in_monitoring(s, job))
    plan = index(lambda s: "terraform plan" in str(s.get("run", "")) and _in_monitoring(s, job))
    apply = index(lambda s: "terraform apply" in str(s.get("run", "")) and _in_monitoring(s, job))
    assert credentials < init < plan < apply

    assert steps[credentials]["with"]["role-to-assume"] == (
        f"arn:aws:iam::{ACCOUNT_ID}:role/{NAME_ROOT}-monitoring-ci-apply"
    )
    assert steps[init]["with"]["args"] == "-backend-config=backend/prod.hcl"
    assert "-out=tfplan" in steps[plan]["run"]
    assert steps[apply]["run"].rstrip().endswith("tfplan")
