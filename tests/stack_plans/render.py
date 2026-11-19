"""Render the tfvars the stack plan tests run against, through the CLI's own code.

Usage: python -m tests.stack_plans.render OUT_DIR

Writes OUT_DIR/<stack>/<case>.tfvars.json, one directory per stack under stacks/,
each case matching tests/stack_plans/<stack>/<case>.tftest.hcl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from jaws.access import (
    Access,
    DirectoryProjectFiles,
    compute_access,
    load_registry,
)
from jaws.project import Project
from jaws.settings import Settings, load_settings
from jaws.site import SiteConfig
from jaws.stack import render_tfvars
from tests.conftest import (
    BRAVEHEART_GUARDRAILS,
    FIXTURES,
    MATH_PROVER_GUARDRAILS,
    REPO_ROOT,
    management_only,
    with_guardrails,
)

#: What the account stack's outputs look like after an apply (`terraform output -json`),
#: for the workspace stack's plan. The tftest file overrides the metastore lookup
#: with the same metastore ID.
ACCOUNT_OUTPUTS: dict[str, Any] = {
    "workspace_id": 1234567890123456,
    "workspace_url": "https://dbc-01234567-89ab.cloud.databricks.com",
    "admin_group_name": "databricks-poc-workspace-admins",
    "users_group_name": "databricks-poc-workspace-users",
    "metastore_id": "abcdef01-2345-6789-abcd-ef0123456789",
    "root_bucket_name": "jwall-engineering-databricks-poc-databricks-root",
}


def _file(name: str) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((FIXTURES / "bots" / f"{name}.yaml").read_text())
    return raw


def _registered(name: str) -> dict[str, Any]:
    """A registered project's own file (tests/fixtures/registry/), as it is live."""
    raw: dict[str, Any] = yaml.safe_load((FIXTURES / "registry" / f"{name}.yaml").read_text())
    return raw


def _dataset_only() -> dict[str, Any]:
    raw = _file("math-prover")
    raw["components"] = [c for c in raw["components"] if c["kind"] == "dataset"]
    return raw


def _scheduled() -> dict[str, Any]:
    """The braveheart sample with running hours: 08:00-20:00 UTC on weekdays."""
    raw = _file("braveheart")
    bot = next(c for c in raw["components"] if c["kind"] == "lichess-bot")
    bot["schedule"] = {"days": "weekdays", "start": "08:00", "stop": "20:00"}
    return raw


def _bot_in_production() -> dict[str, Any]:
    """braveheart-bot's live file as the production view renders it while it moves:
    its tags as the file states them (Organization: jwall-engineering), its token
    parameter under production's prefix (an absolute secret path is one account's)."""
    raw = _registered("braveheart-bot")
    bot = next(c for c in raw["components"] if c["kind"] == "lichess-bot")
    bot["secrets"] = {"LICHESS_TOKEN": "/jaws/braveheart-bot/lichess-token"}
    return raw


def _project(raw: dict[str, Any], settings: Settings) -> Project:
    """`Project.from_config` runs the guardrails."""
    return Project.from_config(SiteConfig.model_validate(raw), settings)


def _handshakes() -> Access:
    """The registry fixtures' handshakes, between the live files in fixtures/registry/."""
    registry = load_registry(FIXTURES / "datasets")
    files = DirectoryProjectFiles(FIXTURES / "registry")
    projects = ("braveheart-selfplay", "braveheart-databricks")
    return compute_access(registry, {name: files.load(name) for name in projects})


TRAINER = "braveheart-trainer"


def _moving(settings: Settings, project: str) -> Settings:
    """`settings` with `project` moving, whatever config.yaml says today."""
    assert settings.production is not None
    projects = {**settings.production.projects, project: "moving"}
    production = settings.production.model_copy(update={"projects": projects})
    return settings.model_copy(update={"production": production})


def cases(settings: Settings) -> dict[str, dict[str, dict[str, Any]]]:
    """Each test file's inputs: by stack (its directory under stacks/), then by case name."""
    research = with_guardrails(settings, "math-prover", MATH_PROVER_GUARDRAILS)
    # The braveheart sample keeps its own central entry: the real engine's shrank at the split.
    sample = with_guardrails(settings, "braveheart", BRAVEHEART_GUARDRAILS)
    production = load_settings(REPO_ROOT / "config.yaml", environ={}, account="production")
    handshakes = _handshakes()
    # The two dataset projects as each case states, not as config.yaml has them
    # today: neither moving, or braveheart-selfplay moving with trainer still
    # management-only (the first step of their move, docs/datasets.md).
    dataset_projects = ("braveheart-selfplay", "braveheart-trainer")
    still = management_only(settings, *dataset_projects)
    selfplay_moving = _moving(still, "braveheart-selfplay")
    selfplay_in_production = _moving(
        management_only(production, *dataset_projects), "braveheart-selfplay"
    )
    both_in_production = _moving(selfplay_in_production, TRAINER)
    bots = {
        "braveheart": (_file("braveheart"), sample),
        "scheduled_bot": (_scheduled(), sample),
        "selfplay": (_registered("braveheart-selfplay"), still),
        "trainer": (_registered("braveheart-trainer"), still),
        "selfplay_moving": (_registered("braveheart-selfplay"), selfplay_moving),
        "selfplay_in_production": (_registered("braveheart-selfplay"), selfplay_in_production),
        # The second step: braveheart-trainer moving too.
        "trainer_moving": (_registered("braveheart-trainer"), _moving(selfplay_moving, TRAINER)),
        "trainer_in_production": (_registered("braveheart-trainer"), both_in_production),
        "selfplay_joined_in_production": (_registered("braveheart-selfplay"), both_in_production),
        "math_prover": (_file("math-prover"), research),
        "dataset_only": (_dataset_only(), research),
        "production_bot": (_bot_in_production(), production),
    }
    databricks = _project(_file("databricks-poc"), settings)
    return {
        "bot": {
            name: render_tfvars(_project(raw, s), s, access=handshakes)
            for name, (raw, s) in bots.items()
        },
        "databricks-account": {
            "databricks_poc": render_tfvars(databricks, settings, stack="account"),
        },
        "databricks-workspace": {
            "databricks_poc": render_tfvars(
                databricks, settings, stack="workspace", account_outputs=ACCOUNT_OUTPUTS
            ),
        },
    }


def main(out: Path) -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", environ={})
    for stack, stack_cases in cases(settings).items():
        (out / stack).mkdir(parents=True, exist_ok=True)
        for name, tfvars in stack_cases.items():
            (out / stack / f"{name}.tfvars.json").write_text(json.dumps(tfvars, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
