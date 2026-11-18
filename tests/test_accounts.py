"""Account views: one configuration, read for the management or the production account.

`config.yaml` describes the management account, where everything lives today,
and one `production:` section says what differs in the production account and
which projects have a stack there. A project is addressed in exactly one
account per run, and every workflow asks the tool which (`config env`).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from jaws import cli
from jaws.errors import ConfigError
from jaws.settings import ProductionSection, Settings, load_settings, resolve_account
from tests.conftest import FIXTURES, REPO_ROOT

runner = CliRunner()
MANAGEMENT = "650503560686"
PRODUCTION = "570327089884"
SITE = "guitar-knowledge-base"  # the project of the `workspace` fixture


def _raw() -> dict[str, Any]:
    """config.yaml before production is bootstrapped and before anything moves,
    whatever the repository's own file says today: these tests must not start
    failing on the pull request that records the bootstrap."""
    raw = yaml.safe_load((FIXTURES / "config.yaml").read_text())
    assert isinstance(raw, dict)
    production = raw["production"]
    production["bootstrapped"] = False
    production["projects"] = {}
    production["overrides"]["aws"].pop("admin_role_arn", None)
    production["overrides"].pop("dns", None)
    return raw


@pytest.fixture(autouse=True)
def _before_the_bootstrap(request: pytest.FixtureRequest) -> None:
    """Every command-line test starts from that same baseline."""
    if "workspace" in request.fixturenames:
        _write(request.getfixturevalue("workspace") / "config.yaml", _raw())


def _write(path: Path, raw: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def _config(tmp_path: Path, projects: dict[str, str]) -> Path:
    raw = _raw()
    raw["production"]["projects"] = projects
    return _write(tmp_path / "config.yaml", raw)


def _section(projects: dict[str, str]) -> ProductionSection:
    return ProductionSection.model_validate({**_raw()["production"], "projects": projects})


# -- which account a run addresses ---------------------------------------------------


@pytest.mark.parametrize(
    ("state", "requested", "expected"),
    [
        (None, None, "management"),
        ("moving", None, "production"),
        ("moving", "management", "management"),
        ("moving", "production", "production"),
        ("moved", None, "production"),
        ("moved", "production", "production"),
    ],
)
def test_a_project_is_addressed_where_it_lives(
    state: str | None, requested: Any, expected: str
) -> None:
    section = _section({"p": state} if state else {})
    assert resolve_account("p", section, requested) == expected


def test_a_run_without_a_project_addresses_management_unless_told() -> None:
    section = _section({})
    assert resolve_account(None, section, None) == "management"
    assert resolve_account(None, section, "production") == "production"
    assert resolve_account(None, section, "management") == "management"


def test_a_project_that_is_not_in_production_cannot_be_addressed_there() -> None:
    with pytest.raises(ConfigError, match="p is not in production"):
        resolve_account("p", _section({}), "production")


def test_a_moved_project_cannot_be_addressed_in_management() -> None:
    with pytest.raises(ConfigError, match="p has left the management account"):
        resolve_account("p", _section({"p": "moved"}), "management")


def test_without_a_production_section_everything_is_management() -> None:
    assert resolve_account("p", None, None) == "management"
    assert resolve_account(None, None, "management") == "management"
    with pytest.raises(ConfigError, match="no production section"):
        resolve_account(None, None, "production")


# -- the two views ---------------------------------------------------------------------


def test_the_management_view_is_the_configuration_as_written() -> None:
    raw = _raw()
    raw.pop("production")
    before = Settings.model_validate(raw).model_dump()
    now = load_settings(FIXTURES / "config.yaml", environ={}).model_dump()
    assert now.pop("account") == "management"
    assert now.pop("organizations") == ("jwall-engineering", "jaws")
    now.pop("production")
    before.pop("account")
    before.pop("organizations")
    before.pop("production")
    assert now == before


def test_the_production_view_is_the_production_account() -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", environ={}, account="production")
    assert settings.account == "production"
    assert settings.aws.account_id == PRODUCTION
    assert settings.context.organization == "jaws"
    assert settings.state.bucket == "jaws-terraform-state-570327089884"
    assert settings.ecr.repository == "jaws-cli"
    assert settings.databricks is not None and settings.databricks.enabled is False


def test_the_production_view_shares_everything_it_does_not_override() -> None:
    management = load_settings(REPO_ROOT / "config.yaml", environ={})
    production = load_settings(REPO_ROOT / "config.yaml", environ={}, account="production")
    assert production.context.owner == management.context.owner
    assert production.state.region == management.state.region
    assert production.state.key_template == management.state.key_template
    assert production.ecr.keep_release_images == management.ecr.keep_release_images
    assert production.terraform == management.terraform
    assert production.library == management.library
    assert production.tasks == management.tasks
    assert production.projects == management.projects
    assert production.production == management.production


def test_production_names_its_own_databricks_resources() -> None:
    """Databricks is off in production, but its roles' policies are created
    there at the bootstrap and must not name the management account's."""
    production = load_settings(REPO_ROOT / "config.yaml", environ={}, account="production")
    assert production.databricks is not None
    assert production.databricks.secret_parameter == "/jaws/databricks/client-secret"
    assert production.databricks.audit_bucket == "jaws-databricks-audit-logs"
    assert production.databricks.metastore_name == "jaws-us-east-1"
    management = load_settings(REPO_ROOT / "config.yaml", environ={})
    assert management.databricks is not None
    assert management.databricks.secret_parameter == "/jwall-engineering/databricks/client-secret"


@pytest.mark.parametrize("section", ["tasks", "projects", "bot", "terraform", "library"])
def test_only_what_differs_between_accounts_can_be_overridden(tmp_path: Path, section: str) -> None:
    """The foundation applies the same overrides (foundation/accounts.tf); a
    section it does not read per account must not differ for the tool either,
    or the tool's guardrails and the roles' IAM would disagree."""
    raw = _raw()
    raw["production"]["overrides"][section] = {}
    with pytest.raises(ConfigError, match=rf"production\.overrides\.{section}.*cannot differ"):
        load_settings(_write(tmp_path / "config.yaml", raw), environ={})


def test_the_tool_and_the_foundation_override_the_same_sections() -> None:
    from jaws.settings import OVERRIDABLE_SECTIONS

    accounts_tf = (REPO_ROOT / "foundation" / "accounts.tf").read_text()
    block = accounts_tf[
        accounts_tf.index("  account = {") : accounts_tf.index(
            "  }\n", accounts_tf.index("  account = {")
        )
    ]
    in_foundation = set(re.findall(r"^    (\w+)\s+=", block, re.MULTILINE))
    # `dns` is the tool's alone: the foundation creates the zone, it does not read its ID.
    assert in_foundation == set(OVERRIDABLE_SECTIONS) - {"dns"}


def test_an_override_for_a_section_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    raw = _raw()
    raw["production"]["overrides"]["nonsense"] = {"a": 1}
    with pytest.raises(ConfigError, match=r"production\.overrides\.nonsense"):
        load_settings(_write(tmp_path / "config.yaml", raw), environ={})


def test_an_override_for_an_optional_section_the_file_leaves_out_is_ignored(
    tmp_path: Path,
) -> None:
    """`databricks` is optional: a configuration without it has nothing to
    override, and its production view has no Databricks either."""
    raw = _raw()
    raw.pop("databricks")
    raw["projects"] = {n: g for n, g in raw["projects"].items() if "databricks" not in (g or {})}
    path = _write(tmp_path / "config.yaml", raw)
    assert load_settings(path, environ={}).databricks is None
    assert load_settings(path, environ={}, account="production").databricks is None


def test_an_override_for_a_key_the_section_does_not_have_is_refused(tmp_path: Path) -> None:
    raw = _raw()
    raw["production"]["overrides"]["aws"]["acount_id"] = PRODUCTION
    with pytest.raises(ConfigError, match="acount_id"):
        load_settings(_write(tmp_path / "config.yaml", raw), environ={}, account="production")


def test_a_broken_production_section_is_refused_in_the_management_view_too(
    tmp_path: Path,
) -> None:
    """A typo in production must fail the pull request that makes it, whichever
    account that pull request's jobs happen to address."""
    raw = _raw()
    raw["production"]["overrides"]["aws"]["account_id"] = "not-an-account"
    with pytest.raises(ConfigError, match="account_id"):
        load_settings(_write(tmp_path / "config.yaml", raw), environ={})


def test_production_is_not_bootstrapped_without_its_zone_and_admin_role(tmp_path: Path) -> None:
    raw = _raw()
    raw["production"]["bootstrapped"] = True
    with pytest.raises(ConfigError, match=r"bootstrapped.*dns\.zone_id.*aws\.admin_role_arn"):
        load_settings(_write(tmp_path / "config.yaml", raw), environ={})


def test_a_bootstrapped_production_account_names_its_zone_and_admin_role(tmp_path: Path) -> None:
    raw = _raw()
    raw["production"]["bootstrapped"] = True
    raw["production"]["overrides"]["dns"] = {"zone_id": "Z0PRODUCTIONZONE0000"}
    raw["production"]["overrides"]["aws"]["admin_role_arn"] = (
        f"arn:aws:iam::{PRODUCTION}:role/aws-reserved/sso.amazonaws.com/"
        "AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    )
    path = _write(tmp_path / "config.yaml", raw)
    production = load_settings(path, environ={}, account="production")
    assert production.dns.zone_id == "Z0PRODUCTIONZONE0000"
    assert production.dns.zone == "jwall.engineering"
    assert load_settings(path, environ={}).dns.zone_id != "Z0PRODUCTIONZONE0000"


def test_a_project_state_other_than_moving_or_moved_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"production\.projects\.p"):
        load_settings(_config(tmp_path, {"p": "here"}), environ={})


# -- the command line --------------------------------------------------------------------


def _env(result: Any) -> dict[str, str]:
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert all("=" in line for line in lines), lines
    return dict(line.split("=", 1) for line in lines)


def test_config_env_for_a_project_still_in_management(workspace: Path) -> None:
    assert _env(runner.invoke(cli.app, ["config", "env"])) == {
        "account": "management",
        "account_id": MANAGEMENT,
        "organization": "jwall-engineering",
        "state_bucket": "jwall-engineering-tfstate",
        "ecr_repository": "jwall-engineering-sites",
        "bootstrapped": "false",
    }


def test_config_env_for_a_moving_project_is_production(workspace: Path) -> None:
    _config(workspace, {SITE: "moving"})
    assert _env(runner.invoke(cli.app, ["config", "env"])) == {
        "account": "production",
        "account_id": PRODUCTION,
        "organization": "jaws",
        "state_bucket": "jaws-terraform-state-570327089884",
        "ecr_repository": "jaws-cli",
        "bootstrapped": "false",
    }


def test_the_old_stack_of_a_moving_project_is_addressed_on_request(workspace: Path) -> None:
    _config(workspace, {SITE: "moving"})
    env = _env(runner.invoke(cli.app, ["--account", "management", "config", "env"]))
    assert env["account"] == "management"
    assert env["account_id"] == MANAGEMENT
    assert env["organization"] == "jwall-engineering"


def test_a_moved_project_addressed_in_management_exits_2(workspace: Path) -> None:
    _config(workspace, {SITE: "moved"})
    result = runner.invoke(cli.app, ["--account", "management", "config", "env"])
    assert result.exit_code == 2
    assert f"{SITE} has left the management account" in result.stderr


def test_a_project_not_in_production_addressed_there_exits_2(workspace: Path) -> None:
    result = runner.invoke(cli.app, ["--account", "production", "config", "env"])
    assert result.exit_code == 2
    assert f"{SITE} is not in production" in result.stderr


def test_without_a_project_file_the_account_is_management_unless_told(workspace: Path) -> None:
    (workspace / "jaws.yaml").unlink()
    assert _env(runner.invoke(cli.app, ["config", "env"]))["account"] == "management"
    env = _env(runner.invoke(cli.app, ["--account", "production", "config", "env"]))
    assert env["account_id"] == PRODUCTION


def test_config_env_stdout_is_only_its_six_lines_for_an_old_file_name(workspace: Path) -> None:
    """Workflows append this output to GITHUB_OUTPUT: a warning must not land in it."""
    (workspace / "jaws.yaml").rename(workspace / "jwall-engineering-sites.yaml")
    _config(workspace, {SITE: "moving"})
    result = runner.invoke(cli.app, ["config", "env"])
    assert len(result.stdout.splitlines()) == 6
    assert _env(result)["account"] == "production"
    assert "old name" in result.stderr


def test_a_project_file_that_cannot_be_parsed_keeps_its_own_error(
    workspace: Path, fake_terraform: Path
) -> None:
    (workspace / "jaws.yaml").write_text("project: [unclosed\n")
    assert _env(runner.invoke(cli.app, ["config", "env"]))["account"] == "management"
    result = runner.invoke(cli.app, ["validate"])
    assert result.exit_code == 2
    assert "jaws.yaml" in result.output


def test_config_show_says_which_account_it_shows(workspace: Path) -> None:
    _config(workspace, {SITE: "moving"})
    shown = json.loads(runner.invoke(cli.app, ["config", "show"]).stdout)
    assert shown["account"] == "production"
    assert shown["aws"]["account_id"] == PRODUCTION
    assert shown["production"]["projects"] == {SITE: "moving"}


# -- a workflow names the project itself ---------------------------------------------------


def test_config_env_for_a_named_project_ignores_the_file_in_the_directory(workspace: Path) -> None:
    """Bot apply and the plan jobs run from the tool's checkout and name the
    project from their matrix or input, before any project file is trusted."""
    _config(workspace, {"braveheart-trainer": "moving"})
    env = _env(runner.invoke(cli.app, ["config", "env", "--project", "braveheart-trainer"]))
    assert env["account"] == "production"
    assert env["organization"] == "jaws"
    assert _env(runner.invoke(cli.app, ["config", "env"]))["account"] == "management"


def test_config_env_for_a_named_project_honours_the_requested_account(workspace: Path) -> None:
    (workspace / "jaws.yaml").unlink()
    _config(workspace, {"braveheart-trainer": "moving"})
    env = _env(
        runner.invoke(
            cli.app, ["--account", "management", "config", "env", "--project", "braveheart-trainer"]
        )
    )
    assert env["account"] == "management"
    assert env["account_id"] == MANAGEMENT


def test_config_env_for_a_named_project_that_has_not_moved_is_management(workspace: Path) -> None:
    _config(workspace, {"braveheart-trainer": "moving"})
    env = _env(runner.invoke(cli.app, ["config", "env", "--project", "braveheart-bot"]))
    assert env["account"] == "management"


def test_config_env_refuses_a_named_project_where_it_has_no_stack(workspace: Path) -> None:
    (workspace / "jaws.yaml").unlink()
    result = runner.invoke(
        cli.app, ["--account", "production", "config", "env", "--project", "braveheart-bot"]
    )
    assert result.exit_code == 2
    assert "braveheart-bot is not in production" in result.stderr
    assert result.stdout == ""


# -- the accounts the foundation is planned and applied for --------------------------------


def _bootstrapped_config(directory: Path) -> Path:
    raw = _raw()
    raw["production"]["bootstrapped"] = True
    raw["production"]["overrides"]["dns"] = {"zone_id": "Z0PRODUCTIONZONE0000"}
    raw["production"]["overrides"]["aws"]["admin_role_arn"] = (
        f"arn:aws:iam::{PRODUCTION}:role/aws-reserved/sso.amazonaws.com/"
        "AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    )
    return _write(directory / "config.yaml", raw)


def test_only_management_is_listed_until_production_is_bootstrapped(workspace: Path) -> None:
    result = runner.invoke(cli.app, ["config", "accounts"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {
            "account": "management",
            "account_id": MANAGEMENT,
            "organization": "jwall-engineering",
            "state_bucket": "jwall-engineering-tfstate",
            "ecr_repository": "jwall-engineering-sites",
        }
    ]


def test_a_bootstrapped_production_account_is_listed_after_management(workspace: Path) -> None:
    _bootstrapped_config(workspace)
    result = runner.invoke(cli.app, ["config", "accounts"])
    assert result.exit_code == 0, result.output
    management, production = json.loads(result.stdout)
    assert management["account"] == "management" and management["account_id"] == MANAGEMENT
    assert production == {
        "account": "production",
        "account_id": PRODUCTION,
        "organization": "jaws",
        "state_bucket": "jaws-terraform-state-570327089884",
        "ecr_repository": "jaws-cli",
    }


def test_the_accounts_are_one_line_of_json_for_a_workflow_output(workspace: Path) -> None:
    """A workflow writes `accounts=<this>` to GITHUB_OUTPUT: one line, nothing else."""
    _bootstrapped_config(workspace)
    result = runner.invoke(cli.app, ["config", "accounts"])
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("\n")


def test_the_accounts_do_not_depend_on_the_project_in_the_directory(workspace: Path) -> None:
    _bootstrapped_config(workspace)
    raw = yaml.safe_load((workspace / "config.yaml").read_text())
    raw["production"]["projects"] = {SITE: "moved"}
    _write(workspace / "config.yaml", raw)
    accounts = json.loads(runner.invoke(cli.app, ["config", "accounts"]).stdout)
    assert [a["account"] for a in accounts] == ["management", "production"]


# -- destroying a project that is moving -----------------------------------------------------


def test_destroying_a_moving_project_needs_the_account_named(bot_workspace: Path) -> None:
    """Both stacks exist; the default (production) is the new one, and the one
    usually meant is the old. Never guess."""
    _config(bot_workspace, {"braveheart": "moving"})
    result = runner.invoke(cli.app, ["destroy", "--yes"])
    assert result.exit_code == 2
    assert "braveheart has a stack in both accounts" in result.output
    assert "--account management" in result.output and "--account production" in result.output


@pytest.mark.parametrize("account", ["management", "production"])
def test_a_named_account_gets_past_that_refusal(bot_workspace: Path, account: str) -> None:
    _config(bot_workspace, {"braveheart": "moving"})
    result = runner.invoke(cli.app, ["--account", account, "destroy", "--yes"])
    assert "has a stack in both accounts" not in result.output


def test_destroying_a_project_in_one_account_needs_no_flag(bot_workspace: Path) -> None:
    _write(bot_workspace / "config.yaml", _raw())
    result = runner.invoke(cli.app, ["destroy", "--yes"])
    assert "has a stack in both accounts" not in result.output


# -- the old stack of a site that is moving --------------------------------------------------

SITE_APPLY_ROLE = f"arn:aws:sts::{MANAGEMENT}:assumed-role/jwall-engineering-{SITE}-ci-apply/s"


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_a_site_that_is_not_moving_is_not_destroyed(workspace: Path, fake_terraform: Path) -> None:
    with patch("jaws.aws.caller_identity", return_value=(MANAGEMENT, SITE_APPLY_ROLE)):
        result = runner.invoke(cli.app, ["--account", "management", "destroy", "--yes"])
    assert result.exit_code == 3
    assert "not supported for sites" in result.output
    assert not any(c.startswith("destroy") for c in _calls(fake_terraform))


def test_destroying_a_moving_site_needs_the_account_named(workspace: Path) -> None:
    _config(workspace, {SITE: "moving"})
    result = runner.invoke(cli.app, ["destroy", "--yes"])
    assert result.exit_code == 2
    assert f"{SITE} has a stack in both accounts" in result.output


def test_a_moving_site_s_production_stack_is_not_destroyed(
    workspace: Path, fake_terraform: Path
) -> None:
    _config(workspace, {SITE: "moving"})
    result = runner.invoke(cli.app, ["--account", "production", "destroy", "--yes"])
    assert result.exit_code == 3
    assert "a site's production stack is not destroyed by the tool" in result.output
    assert not any(c.startswith("destroy") for c in _calls(fake_terraform))


def test_destroying_a_moving_site_s_old_stack_needs_yes(
    workspace: Path, fake_terraform: Path
) -> None:
    _config(workspace, {SITE: "moving"})
    with patch("jaws.aws.caller_identity", return_value=(MANAGEMENT, SITE_APPLY_ROLE)):
        result = runner.invoke(cli.app, ["--account", "management", "destroy"])
    assert result.exit_code == 3
    assert "pass --yes" in result.output
    for goes in ("distributions", "certificates", "records"):
        assert goes in result.output
    assert "jwall-engineering-guitar-knowledge-base" in result.output  # the bucket, which stays
    assert not any(c.startswith("destroy") for c in _calls(fake_terraform))


def test_the_old_stack_of_a_moving_site_is_destroyed(workspace: Path, fake_terraform: Path) -> None:
    _config(workspace, {SITE: "moving"})
    with patch("jaws.aws.caller_identity", return_value=(MANAGEMENT, SITE_APPLY_ROLE)):
        result = runner.invoke(cli.app, ["--account", "management", "destroy", "--yes"])
    assert result.exit_code == 0, result.output
    calls = _calls(fake_terraform)
    assert any(c.startswith("destroy") for c in calls)
    assert not any(c.startswith("state rm") for c in calls)
    rendered = json.loads(Path(os.environ["FAKE_TF_TFVARS"]).read_text())
    assert rendered["tags"]["Organization"] == "jwall-engineering"  # the management stack
