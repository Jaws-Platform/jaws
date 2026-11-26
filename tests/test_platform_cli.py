"""`jaws platform plan|apply`: the platform's own stacks, run as a hub's workflows run them.

Each stack is one `main.tf` under JAWS_STACKS_ROOT, as the image keeps them, and Terraform
is the fake (tests/fixtures/bin/terraform). A test takes on a role as tests/test_cli.py's
`_as_role` does. The Databricks secret is SECRET (`_no_aws`), so no test can read a real one.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import ANY, MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner, Result

from jaws import cli
from jaws.databricks_auth import load_secret as real_load_secret  # `_no_aws` patches the module's
from jaws.platform import PlatformTerraform, platform_backend, platform_stack
from jaws.settings import load_settings
from tests.conftest import CONFIG_DIR, FIXTURES

runner = CliRunner()
#: The platform's stacks, each a root module the image holds.
STACKS = ("foundation", "monitoring", "data-access")
SECRET = "dbx-secret-value"
#: The fixture's databricks.secret_parameter.
SECRET_PARAMETER = "/jaws/databricks/client-secret"


def _as_role(role: str) -> AbstractContextManager[Any]:
    """Credentials that are a session of the role `role` in the fixture's account."""
    arn = f"arn:aws:sts::222222222222:assumed-role/{role}/s"
    return patch("jaws.aws.caller_identity", return_value=("222222222222", arn))


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """The Databricks secret is SECRET, and AWS has no profile, keys or files to read
    another with. Yields the patched `load_secret`."""
    for name in (
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    with patch("jaws.databricks_auth.load_secret", return_value=SECRET) as load_secret:
        yield load_secret


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_terraform: Path) -> Path:
    """Where the CLI runs: the neutral configuration as config/, with the onboarded datasets
    beside it (JAWS_INFRA_ROOT) and the two project files that agree one handshake
    (JAWS_PROJECT_FILES_DIR), which data access reads. The stacks are under JAWS_STACKS_ROOT,
    and GITHUB_OUTPUT and the step summary are files beside this directory."""
    root = tmp_path / "work"
    shutil.copytree(CONFIG_DIR, root / "config")
    shutil.copytree(FIXTURES / "datasets", root / "datasets")
    files = tmp_path / "project-files"
    files.mkdir()
    for name in ("braveheart-selfplay", "braveheart-databricks"):
        shutil.copy(FIXTURES / "registry" / f"{name}.yaml", files / f"{name}.yaml")
    monkeypatch.setenv("JAWS_PROJECT_FILES_DIR", str(files))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    for name in STACKS:
        directory = tmp_path / "stacks" / name
        directory.mkdir(parents=True)
        (directory / "main.tf").write_text("# empty\n")
    monkeypatch.setenv("JAWS_STACKS_ROOT", str(tmp_path / "stacks"))
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.chdir(root)
    return root


def _platform(work: Path, *args: str) -> Result:
    """`jaws platform <args>`, reading the work directory's configuration."""
    return runner.invoke(cli.app, ["--config", str(work / "config"), "platform", *args])


def _calls(log: Path) -> list[str]:
    """The fake terraform's invocations, without its version checks."""
    return [c for c in log.read_text().splitlines() if not c.startswith("version")]


def _outputs(work: Path) -> list[str]:
    """The lines the command appended to GITHUB_OUTPUT."""
    path = work.parent / "github-output"
    return path.read_text().splitlines() if path.exists() else []


def _summary(work: Path) -> str:
    path = work.parent / "summary.md"
    return path.read_text() if path.exists() else ""


def _terraform_env(path: Path) -> dict[str, str]:
    """The environment the fake terraform ran with (FAKE_TF_ENV): each variable's last value."""
    return {
        key: value
        for key, value in (
            line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
        )
    }


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("foundation", "project=infra/env=prod/infra-prod.tfstate"),
        ("monitoring", "project=monitoring/env=prod/monitoring-prod.tfstate"),
        ("data-access", "project=data-access/env=prod/data-access-prod.tfstate"),
    ],
)
def test_the_backend_is_today_s_key_in_the_state_bucket(name: str, key: str) -> None:
    settings = load_settings(CONFIG_DIR, environ={})
    assert platform_backend(settings, platform_stack(name)) == (
        'bucket       = "jaws-terraform-state-222222222222"\n'
        f'key          = "{key}"\n'
        'region       = "us-east-1"\n'
        "use_lockfile = true\n"
        "encrypt      = true\n"
    )


@pytest.mark.parametrize("command", ["plan", "apply"])
@pytest.mark.parametrize("name", ["owner-access", "billing-export", "release-infra", "site"])
def test_only_the_platform_s_three_stacks_run(
    work: Path, fake_terraform: Path, command: str, name: str
) -> None:
    result = _platform(work, command, name)
    assert result.exit_code == 2, result.output
    assert (
        f"{name} is not one of the platform's stacks: foundation, monitoring, data-access"
        in result.output
    )
    assert not fake_terraform.exists(), "terraform must not run for any other stack"


@pytest.mark.parametrize(
    ("command", "name", "role", "other"),
    [
        ("plan", "foundation", "jaws-infra-ci-plan", "jaws-infra-ci-apply"),
        ("apply", "foundation", "jaws-infra-ci-apply", "jaws-infra-ci-plan"),
        ("plan", "monitoring", "jaws-monitoring-ci-plan", "jaws-infra-ci-plan"),
        ("apply", "data-access", "jaws-data-access-ci-apply", "jaws-infra-ci-apply"),
    ],
)
def test_each_stack_runs_as_its_own_role(
    work: Path,
    fake_terraform: Path,
    _no_aws: MagicMock,
    command: str,
    name: str,
    role: str,
    other: str,
) -> None:
    with _as_role(other):
        refused = _platform(work, command, name)
    assert refused.exit_code == 3, refused.output
    assert f"must run as the {role} role" in refused.output
    assert not fake_terraform.exists(), "terraform must not run after a failed role check"
    assert not _no_aws.called, "no secret is read before the role check"
    with _as_role(role):
        result = _platform(work, command, name)
    assert result.exit_code == 0, result.output


def test_plan_writes_the_comment_under_the_name_root(
    work: Path, fake_terraform: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", "2")
    monkeypatch.setenv("FAKE_TF_PLAN_SUMMARY", "1 to add, 0 to change, 0 to destroy.")
    plugins = tmp_path / "plugins"
    monkeypatch.setenv("JAWS_PLUGIN_DIR", str(plugins))
    with _as_role("jaws-infra-ci-plan"):
        result = _platform(work, "plan", "foundation")
    assert result.exit_code == 0, result.output
    assert "Plan: 1 to add" in (work / ".jaws" / "plan.txt").read_text()
    comment = (work / ".jaws" / "plan-comment.md").read_text()
    assert "<code>jaws/foundation</code>" in comment.splitlines()[1]  # the title's subject
    assert "Changes pending" in comment and "`jaws/foundation`" in comment
    assert _outputs(work) == ["result=changes", "changes=true"]
    assert "Terraform plan: changes" in _summary(work)
    calls = _calls(fake_terraform)
    assert [c.split()[0] for c in calls] == ["init", "plan"]
    init, plan = (c.split() for c in calls)
    assert "-backend-config=backend.hcl" in init
    assert f"-plugin-dir={plugins}" in init, "init takes providers from the image's mirror"
    assert "-detailed-exitcode" in plan


def test_a_failed_plan_exits_1_after_writing_the_comment(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TF_LOCKED", "1")
    with _as_role("jaws-monitoring-ci-plan"):
        result = _platform(work, "plan", "monitoring")
    assert result.exit_code == 1, result.output
    assert "Error acquiring the state lock" in (work / ".jaws" / "plan.txt").read_text()
    comment = (work / ".jaws" / "plan-comment.md").read_text()
    assert "Plan failed" in comment and "Error acquiring the state lock" in comment
    assert "<code>jaws/monitoring</code>" in comment.splitlines()[1]
    assert _outputs(work) == ["result=failed", "changes=false"]


@pytest.mark.parametrize(
    ("plan_exit", "applies", "outcome"), [(0, False, "no-changes"), (2, True, "applied")]
)
def test_apply_applies_only_what_its_plan_found(
    work: Path,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_exit: int,
    applies: bool,
    outcome: str,
) -> None:
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", str(plan_exit))
    with _as_role("jaws-infra-ci-apply"):
        result = _platform(work, "apply", "foundation")
    assert result.exit_code == 0, result.output
    calls = _calls(fake_terraform)
    assert [c.split()[0] for c in calls] == ["init", "plan", *(["apply"] if applies else [])]
    plan = calls[1].split()
    assert "-detailed-exitcode" in plan
    [saved] = [arg.removeprefix("-out=") for arg in plan if arg.startswith("-out=")]
    assert Path(saved).name == "tfplan"
    if applies:
        assert calls[2].split()[-1] == saved, "apply takes the saved plan"
    assert _outputs(work) == [f"result={outcome}"]
    assert f"Terraform apply: {outcome}" in _summary(work)


def test_apply_stops_at_a_failed_plan(
    work: Path, fake_terraform: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TF_LOCKED", "1")
    with _as_role("jaws-infra-ci-apply"):
        result = _platform(work, "apply", "foundation")
    assert result.exit_code == 1, result.output
    assert [c.split()[0] for c in _calls(fake_terraform)] == ["init", "plan"]
    assert _outputs(work) == []


@pytest.mark.parametrize(
    ("name", "role", "variables"),
    [
        ("foundation", "jaws-infra-ci-plan", {"TF_VAR_config_path", "TF_VAR_datasets_path"}),
        ("monitoring", "jaws-monitoring-ci-plan", {"TF_VAR_config_path"}),
        ("data-access", "jaws-data-access-ci-plan", set()),
    ],
)
def test_the_stack_reads_the_cli_s_configuration(
    work: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    role: str,
    variables: set[str],
) -> None:
    env_log = tmp_path / "terraform.env"
    monkeypatch.setenv("FAKE_TF_ENV", str(env_log))
    # Both relative: Terraform runs in a working copy elsewhere, so it gets them made absolute.
    monkeypatch.setenv("JAWS_INFRA_ROOT", ".")
    assert Path.cwd() == work, "the relative paths below must be the work directory's"
    with _as_role(role):
        result = runner.invoke(cli.app, ["--config", "config", "platform", "plan", name])
    assert result.exit_code == 0, result.output
    env = _terraform_env(env_log)
    expected = {
        "TF_VAR_config_path": str(work / "config"),
        "TF_VAR_datasets_path": str(work / "datasets"),  # <infra root>/datasets
    }
    given = {key: env[key] for key in expected if key in env}
    assert given == {key: value for key, value in expected.items() if key in variables}


@pytest.mark.parametrize(
    ("command", "role"), [("plan", "jaws-infra-ci-plan"), ("apply", "jaws-infra-ci-apply")]
)
def test_the_databricks_credential_reaches_terraform_only(
    work: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _no_aws: MagicMock,
    command: str,
    role: str,
) -> None:
    env_log = tmp_path / "terraform.env"
    monkeypatch.setenv("FAKE_TF_ENV", str(env_log))
    monkeypatch.setenv("FAKE_TF_ECHO_SECRET", "1")  # a provider that prints the secret
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", "2")
    with _as_role(role):
        result = _platform(work, command, "foundation")
    assert result.exit_code == 0, result.output
    _no_aws.assert_called_once_with(ANY, SECRET_PARAMETER)
    env = _terraform_env(env_log)
    credential = ("DATABRICKS_ACCOUNT_ID", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET")
    assert {key: env.get(key) for key in credential} == {
        "DATABRICKS_ACCOUNT_ID": "00000000-0000-4000-8000-000000000001",
        "DATABRICKS_CLIENT_ID": "00000000-0000-4000-8000-000000000002",
        "DATABRICKS_CLIENT_SECRET": SECRET,
    }
    assert "provider debug: token request for ***" in result.output, "printed, and masked"
    texts = {
        "console": result.output,
        "GITHUB_OUTPUT": "\n".join(_outputs(work)),
        "GITHUB_STEP_SUMMARY": _summary(work),
        **{p.name: p.read_text() for p in (work / ".jaws").iterdir() if p.is_file()},
    }
    written = {"jaws.log", "plan.txt", "plan-comment.md"} if command == "plan" else {"jaws.log"}
    assert written <= texts.keys()
    assert [where for where, text in texts.items() if SECRET in text] == []


@pytest.mark.parametrize(
    ("name", "role", "enabled"),
    [("monitoring", "jaws-monitoring-ci-plan", True), ("foundation", "jaws-infra-ci-plan", False)],
)
def test_no_credential_where_databricks_is_not_used(
    work: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _no_aws: MagicMock,
    name: str,
    role: str,
    enabled: bool,
) -> None:
    """Monitoring manages nothing in Databricks, and a platform may have it disabled."""
    section = work / "config" / "databricks.yaml"
    document = yaml.safe_load(section.read_text())
    document["databricks"]["enabled"] = enabled
    section.write_text(yaml.safe_dump(document))
    env_log = tmp_path / "terraform.env"
    monkeypatch.setenv("FAKE_TF_ENV", str(env_log))
    with _as_role(role):
        result = _platform(work, "plan", name)
    assert result.exit_code == 0, result.output
    assert not _no_aws.called
    assert "DATABRICKS_CLIENT_SECRET" not in _terraform_env(env_log)


def test_a_secret_of_several_lines_is_refused_before_any_mask(
    work: Path, fake_terraform: Path, monkeypatch: pytest.MonkeyPatch, _no_aws: MagicMock
) -> None:
    """A runner masks only the first line of an `::add-mask::`, so the rest of a secret of
    several lines would print in the job log. It is refused before anything echoes it."""

    class Stored:
        def get_parameter(self, **kwargs: Any) -> Any:
            return {"Parameter": {"Value": "first-half\nsecond-half"}}

    def read(ssm: object, parameter: str) -> str:
        return real_load_secret(Stored(), parameter)  # the real refusal, with no AWS

    _no_aws.side_effect = read
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with _as_role("jaws-infra-ci-plan"):
        result = _platform(work, "plan", "foundation")
    assert result.exit_code == 3, result.output
    assert SECRET_PARAMETER in result.output
    texts = {"console": result.output, "jaws.log": (work / ".jaws" / "jaws.log").read_text()}
    halves = ("first-half", "second-half")
    assert [where for where, text in texts.items() if any(h in text for h in halves)] == []
    assert not fake_terraform.exists(), "terraform must not run without its credential"


def test_the_secret_is_read_in_the_product_region(work: Path, _no_aws: MagicMock) -> None:
    """The stacks build in us-east-1 (spec 6.7), where the foundation grants the secret's
    parameter. A state bucket elsewhere changes only the backend's region."""
    section = work / "config" / "terraform.yaml"
    document = yaml.safe_load(section.read_text())
    document["state"]["region"] = "us-west-2"
    section.write_text(yaml.safe_dump(document))
    with _as_role("jaws-infra-ci-plan") as identity:
        result = _platform(work, "plan", "foundation")
    assert result.exit_code == 0, result.output
    [(sts,)] = [call.args for call in identity.call_args_list]
    [(ssm, parameter)] = [call.args for call in _no_aws.call_args_list]
    assert (sts.meta.region_name, ssm.meta.region_name) == ("us-east-1", "us-east-1")
    assert parameter == SECRET_PARAMETER
    settings = load_settings(work / "config", environ={})
    backend = platform_backend(settings, platform_stack("foundation"))
    assert 'region       = "us-west-2"\n' in backend


def test_the_working_copy_holds_the_stack_and_its_backend(
    work: Path, logger: logging.Logger
) -> None:
    settings = load_settings(work / "config", environ={})
    monitoring = platform_stack("monitoring")
    terraform = PlatformTerraform(monitoring, settings, logger)
    workdir = terraform.prepare()
    try:
        assert (workdir / "main.tf").read_text() == "# empty\n"
        assert (workdir / "backend.hcl").read_text() == platform_backend(settings, monitoring)
        assert json.loads((workdir / "terraform.tfvars.json").read_text()) == {}
    finally:
        terraform.cleanup(failed=False)
    assert not workdir.exists()


# -- data access: the render, then the stack --------------------------------------------


@pytest.mark.parametrize(
    ("command", "role"),
    [("plan", "jaws-data-access-ci-plan"), ("apply", "jaws-data-access-ci-apply")],
)
@pytest.mark.parametrize(
    ("document", "state"),
    [({"enabled": False}, "disabled"), ({"shared_host_url": None}, "awaiting-host")],
)
def test_data_access_waits_for_databricks(
    work: Path,
    fake_terraform: Path,
    _no_aws: MagicMock,
    caplog: pytest.LogCaptureFixture,
    command: str,
    role: str,
    document: dict[str, Any],
    state: str,
) -> None:
    section = work / "config" / "databricks.yaml"
    config = yaml.safe_load(section.read_text())
    config["databricks"].update(document)
    section.write_text(yaml.safe_dump(config))
    # No role is assumed: a platform without Databricks never calls AWS.
    result = _platform(work, command, "data-access")
    assert result.exit_code == 0, result.output
    assert f"Databricks is {state}: nothing to reconcile" in result.output
    assert _outputs(work) == ["result=skipped"]
    assert not (work / ".jaws" / "plan-comment.md").exists()
    assert _summary(work) == ""
    assert not fake_terraform.exists(), "terraform must not run"
    assert not _no_aws.called


def test_the_data_access_plan_renders_against_the_base_registry(
    work: Path,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rendered = tmp_path / "rendered.tfvars.json"  # the fake copies the working copy's at init
    out = tmp_path / "access-out"
    runner.invoke(
        cli.app, ["--config", str(work / "config"), "access", "render", "--out", str(out)]
    )
    expected = json.loads((out / "terraform.tfvars.json").read_text())
    assert expected["datasets"], "the registry fixture onboards a dataset"
    base = tmp_path / "base-datasets"
    shutil.copytree(FIXTURES / "datasets", base)
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", "2")
    with _as_role("jaws-data-access-ci-plan"):
        result = _platform(work, "plan", "data-access", "--base-registry", str(base))
    assert result.exit_code == 0, result.output
    assert json.loads(rendered.read_text()) == expected
    summary = (out / "access-summary.md").read_text()
    comment = (work / ".jaws" / "plan-comment.md").read_text()
    assert comment.endswith("\n" + summary), "the plan comment, a blank line, the access summary"
    assert "<code>jaws/data-access</code>" in comment.splitlines()[1]
    assert _outputs(work) == ["result=changes", "changes=true"]
    assert [c.split()[0] for c in _calls(fake_terraform)] == ["init", "plan"]


def test_the_data_access_plan_refuses_an_offboarding_a_handshake_still_names(
    work: Path,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "infra"
    shutil.copytree(FIXTURES / "datasets", root / "datasets")
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(root))
    base = tmp_path / "base-datasets"
    shutil.copytree(root / "datasets", base)
    shutil.rmtree(root / "datasets" / "braveheart-selfplay")  # dropped, still named
    with _as_role("jaws-data-access-ci-plan"):
        result = _platform(work, "plan", "data-access", "--base-registry", str(base))
    assert result.exit_code == 2, result.output
    assert "offboarding braveheart-selfplay/positions" in (work / ".jaws" / "jaws.log").read_text()
    assert not fake_terraform.exists(), "no plan runs"
    assert not (work / ".jaws" / "plan-comment.md").exists()


def test_the_data_access_render_refuses_a_missing_registry(
    work: Path, fake_terraform: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(tmp_path))  # no datasets/ here
    with _as_role("jaws-data-access-ci-apply"):
        result = _platform(work, "apply", "data-access")
    assert result.exit_code == 2, result.output
    assert "revoked" in "".join(result.output.split())
    assert not fake_terraform.exists()


def test_the_sweep_summarizes_what_it_applied(
    work: Path,
    fake_terraform: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "sweep-outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "edges": {"value": ["braveheart-databricks reads braveheart-selfplay/positions"]},
                "awaiting_onboarding": {"value": []},
                "missing_workspaces": {"value": []},
                "fingerprint": {"value": "not shown"},
            }
        )
    )
    monkeypatch.setenv("FAKE_TF_OUTPUTS", str(outputs))
    monkeypatch.setenv("FAKE_TF_PLAN_EXIT", "2")
    with _as_role("jaws-data-access-ci-apply"):
        result = _platform(work, "apply", "data-access")
    assert result.exit_code == 0, result.output
    assert [c.split()[0] for c in _calls(fake_terraform)][:3] == ["init", "plan", "apply"]
    assert _outputs(work) == ["result=applied"]
    summary = _summary(work)
    assert summary.startswith("**Sweep: applied**\n\n")
    assert "braveheart-databricks" in summary
    _, _, state = summary.partition("### Applied state\n\n```json\n")
    assert json.loads(state.split("```")[0]) == {
        "edges": ["braveheart-databricks reads braveheart-selfplay/positions"],
        "awaiting_onboarding": [],
        "missing_workspaces": [],
    }


def test_a_failed_sweep_says_so_in_its_summary(
    work: Path, fake_terraform: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_TF_LOCKED", "1")  # the plan fails
    with _as_role("jaws-data-access-ci-apply"):
        result = _platform(work, "apply", "data-access")
    assert result.exit_code == 1, result.output
    summary = _summary(work)
    assert summary.startswith("**Sweep: failed**\n")
    assert "braveheart-databricks" in summary, "the access summary, as the render got that far"
    assert "Applied state" not in summary
    assert not any(line.startswith("result=") for line in _outputs(work))
