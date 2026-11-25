"""The stack plan tests stay wired up, and stay out of the stacks."""

from __future__ import annotations

import os
from typing import Any

import yaml

from jaws.product import product_pins
from jaws.settings import Settings
from tests.conftest import REPO_ROOT, fixture_settings
from tests.stack_plans.render import cases

PLANS = REPO_ROOT / "tests" / "stack_plans"
SCRIPT = REPO_ROOT / "scripts" / "test-stack-plans.sh"


def _settings() -> Settings:
    return fixture_settings(environ={})


def test_every_rendered_case_has_a_test_file_and_the_reverse() -> None:
    rendered = cases(_settings())
    on_disk = {
        p.parent.name: {q.name.split(".")[0] for q in p.parent.glob("*.tftest.hcl")}
        for p in PLANS.glob("*/*.tftest.hcl")
    }
    assert {stack: set(c) for stack, c in rendered.items()} == on_disk
    assert not list(PLANS.glob("*.tftest.hcl")), "test files live in tests/stack_plans/<stack>/"


def test_every_tested_stack_exists() -> None:
    for stack in cases(_settings()):
        assert (REPO_ROOT / "stacks" / stack / "main.tf").is_file(), stack


def test_the_cases_cover_a_bot_a_research_project_and_a_dataset_alone() -> None:
    rendered = cases(_settings())["bot"]
    assert rendered["braveheart"]["bot_enabled"] is True
    assert rendered["math_prover"]["bot_enabled"] is False
    assert rendered["math_prover"]["task_runner_enabled"] is True
    assert rendered["dataset_only"]["bot_enabled"] is False
    assert rendered["dataset_only"]["task_runner_enabled"] is False
    assert [d["name"] for d in rendered["dataset_only"]["datasets"]] == ["artifacts"]


def test_the_databricks_cases_plan_both_stacks_of_one_project() -> None:
    rendered = cases(_settings())
    account = rendered["databricks-account"]["databricks_poc"]
    workspace = rendered["databricks-workspace"]["databricks_poc"]
    assert account["project"] == workspace["project"] == "databricks-poc"


def test_no_test_file_sits_in_a_stack_the_image_copies() -> None:
    stacks = REPO_ROOT / "stacks"
    found = [p for p in stacks.rglob("*.tf*.hcl") if ".terraform" not in p.parts]
    assert [p.name for p in found if p.name != ".terraform.lock.hcl"] == []


def test_ci_runs_the_script_with_the_pinned_terraform() -> None:
    ci: dict[Any, Any] = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["stack-plans"]
    assert job["permissions"] == {"contents": "read"}, "the job needs no AWS role"
    runs = [s.get("run") for s in job["steps"]]
    assert "scripts/test-stack-plans.sh" in runs
    setup = next(s for s in job["steps"] if "setup-terraform" in s.get("uses", ""))
    pinned = product_pins().terraform_version
    assert setup["with"]["terraform_version"] == pinned
    assert setup["with"]["terraform_wrapper"] is False


def test_the_script_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)


def test_every_exact_terraform_version_in_a_workflow_is_the_release_pin() -> None:
    pinned = product_pins().terraform_version
    found = 0
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        doc: dict[Any, Any] = yaml.safe_load(workflow.read_text())
        for name, job in doc["jobs"].items():
            for step in job.get("steps", []):
                version = str((step.get("with") or {}).get("terraform_version", ""))
                if version[:1].isdigit():
                    found += 1
                    assert version == pinned, f"{workflow.name} {name}: {version} != {pinned}"
    assert found


def test_the_relabelled_case_is_another_platform_s() -> None:
    relabelled = cases(_settings())["bot"]["relabelled"]
    assert relabelled["managed_by"] == relabelled["tags"]["ManagedBy"] == "ACME"
    assert relabelled["tags"]["Department"] == "research"
