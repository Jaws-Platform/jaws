"""The monitoring stack is planned on pull requests and applied only on release.

Merging a pull request provisions nothing: CI validates, tests and plans
monitoring/ (with jaws-monitoring-ci-plan) and never applies it; the Release
apply job applies it after the foundation (with jaws-monitoring-ci-apply), so
one release creates the stack's roles and billing bucket, then the stack. Until
the release that creates the plan role, the pull request plan is skipped with a
notice instead of failing.
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


def _in_monitoring(step: dict[str, Any]) -> bool:
    return (step.get("with") or {}).get("working-directory", step.get("working-directory")) == (
        "monitoring"
    )


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
    """Only the Release apply job applies, and only for a release."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in yaml.safe_load(path.read_text())["jobs"].items():
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                in_monitoring = _in_monitoring(step) or (
                    (job.get("defaults") or {}).get("run", {}).get("working-directory")
                    == "monitoring"
                    and "working-directory" not in step
                )
                if in_monitoring and "terraform apply" in run:
                    assert (path.name, name) == ("release-please.yml", "apply"), (path.name, name)
    assert "terraform apply" not in (WORKFLOWS / "ci.yml").read_text()
    apply = _jobs("release-please.yml")["apply"]
    assert apply["if"] == (
        "github.event_name == 'push' && needs.release-please.outputs.release_created == 'true'"
    )


def test_the_release_applies_monitoring_after_the_foundation() -> None:
    steps = _jobs("release-please.yml")["apply"]["steps"]

    def index(predicate: Any) -> int:
        matches = [i for i, s in enumerate(steps) if predicate(s)]
        assert len(matches) == 1, matches
        return matches[0]

    foundation_apply = index(
        lambda s: "terraform apply" in str(s.get("run", "")) and not _in_monitoring(s)
    )
    credentials = index(
        lambda s: (
            _uses(s, "aws-actions/configure-aws-credentials")
            and "monitoring" in s["with"]["role-to-assume"]
        )
    )
    init = index(lambda s: _uses(s, "./.github/actions/terraform-init") and _in_monitoring(s))
    plan = index(lambda s: "terraform plan" in str(s.get("run", "")) and _in_monitoring(s))
    apply = index(lambda s: "terraform apply" in str(s.get("run", "")) and _in_monitoring(s))
    assert foundation_apply < credentials < init < plan < apply

    assert steps[credentials]["with"]["role-to-assume"] == (
        f"arn:aws:iam::{ACCOUNT_ID}:role/{NAME_ROOT}-monitoring-ci-apply"
    )
    assert steps[init]["with"]["args"] == "-backend-config=backend/prod.hcl"
    assert "-out=tfplan" in steps[plan]["run"]
    assert steps[apply]["run"].rstrip().endswith("tfplan")
    for i in (credentials, init, plan, apply):
        assert steps[i]["if"] == CONFIGURED, steps[i]
