"""A research project's datasets while it moves to the production account.

One project file must render in both accounts while the project is `moving`
(Bot apply reads the consumer's main): the bucket is each account's derivation,
whatever the file's `bucket` says; a reader named `<project>/<role>` resolves in
the account addressed, once that project has a stack there; the old buckets let
production's admin role read them, for the server-side copy; and no Databricks
share role is named where Databricks is off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from jaws.errors import ConfigError
from jaws.project import Project
from jaws.settings import Settings
from jaws.site import load_site_config
from jaws.stack import render_tfvars
from tests.conftest import FIXTURES, fixture_settings, management_only, with_guardrails

MANAGEMENT = "650503560686"
PRODUCTION = "570327089884"
PRODUCTION_ADMIN = (
    f"arn:aws:iam::{PRODUCTION}:role/aws-reserved/sso.amazonaws.com/"
    "AWSReservedSSO_AdministratorAccess_013589f39f92382a"
)
OLD_POSITIONS = "jwall-engineering-braveheart-selfplay-positions"
NEW_POSITIONS = "jaws-braveheart-selfplay-positions"


def _view(account: str, projects: dict[str, str] | None = None) -> Settings:
    """config.yaml's fixture in one account's view, with neither project moving
    unless `projects` says so, and both accounts' positions buckets approved."""
    settings = management_only(
        fixture_settings(environ={}, account=account), "braveheart-selfplay", "braveheart-trainer"
    )
    assert settings.production is not None
    production = settings.production.model_copy(
        update={"projects": {**settings.production.projects, **(projects or {})}}
    )
    settings = settings.model_copy(update={"production": production})
    approved = settings.projects["braveheart-selfplay"]
    retention = approved.datasets[OLD_POSITIONS]
    both = approved.model_copy(
        update={"datasets": {OLD_POSITIONS: retention, NEW_POSITIONS: retention}}
    )
    return with_guardrails(settings, "braveheart-selfplay", both)


def _selfplay(tmp_path: Path, **dataset: Any) -> Any:
    """The registry's braveheart-selfplay file, its dataset's fields replaced by `dataset`."""
    raw = yaml.safe_load((FIXTURES / "registry" / "braveheart-selfplay.yaml").read_text())
    (positions,) = [c for c in raw["components"] if c["kind"] == "dataset"]
    positions.update(dataset)
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_site_config(path)


def _dataset(tmp_path: Path, settings: Settings, **dataset: Any) -> dict[str, Any]:
    project = Project.from_config(_selfplay(tmp_path, **dataset), settings)
    (rendered,) = render_tfvars(project, settings)["datasets"]
    result: dict[str, Any] = rendered
    return result


# -- the bucket is the account's ------------------------------------------------


@pytest.mark.parametrize("stated", [OLD_POSITIONS, NEW_POSITIONS])
def test_each_account_renders_its_own_bucket_whatever_the_file_states(
    tmp_path: Path, stated: str
) -> None:
    moving = {"braveheart-selfplay": "moving"}
    assert _dataset(tmp_path, _view("management", moving), bucket=stated)["bucket"] == (
        OLD_POSITIONS
    )
    assert _dataset(tmp_path, _view("production", moving), bucket=stated)["bucket"] == (
        NEW_POSITIONS
    )


def test_a_bucket_under_neither_organization_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as error:
        _dataset(tmp_path, _view("management"), bucket="acme-braveheart-selfplay-positions")
    assert OLD_POSITIONS in str(error.value)
    assert NEW_POSITIONS in str(error.value)


def test_the_approval_is_the_addressed_accounts_bucket(tmp_path: Path) -> None:
    settings = _view("production", {"braveheart-selfplay": "moving"})
    approved = settings.projects["braveheart-selfplay"]
    only_old = approved.model_copy(
        update={"datasets": {OLD_POSITIONS: approved.datasets[OLD_POSITIONS]}}
    )
    settings = with_guardrails(settings, "braveheart-selfplay", only_old)
    with pytest.raises(ConfigError, match=f"bucket '{NEW_POSITIONS}' is not in"):
        _dataset(tmp_path, settings, bucket=OLD_POSITIONS)


# -- readers by project ---------------------------------------------------------


def test_a_reader_by_project_is_the_role_in_the_account_addressed(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path, _view("management"), readers=["braveheart-trainer/task-gpu"])
    assert dataset["readers"] == [
        f"arn:aws:iam::{MANAGEMENT}:role/jwall-engineering-braveheart-trainer-task-gpu"
    ]


def test_a_reader_by_project_waits_until_that_project_is_in_production(
    tmp_path: Path,
) -> None:
    readers = ["braveheart-trainer/task-gpu"]
    alone = _view("production", {"braveheart-selfplay": "moving"})
    assert _dataset(tmp_path, alone, readers=readers)["readers"] == []
    both = _view("production", {"braveheart-selfplay": "moving", "braveheart-trainer": "moving"})
    assert _dataset(tmp_path, both, readers=readers)["readers"] == [
        f"arn:aws:iam::{PRODUCTION}:role/jaws-braveheart-trainer-task-gpu"
    ]


def test_a_reader_by_project_leaves_management_once_that_project_has_moved(
    tmp_path: Path,
) -> None:
    settings = _view("management", {"braveheart-trainer": "moved"})
    assert _dataset(tmp_path, settings, readers=["braveheart-trainer/task-gpu"])["readers"] == []


def test_a_reader_project_must_be_in_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="names project 'no-such-project', which has no entry"):
        _dataset(tmp_path, _view("management"), readers=["no-such-project/task"])


@pytest.mark.parametrize("reader", ["braveheart-trainer", "Braveheart-Trainer/task", "a/b/c"])
def test_a_reader_is_an_arn_or_project_slash_role(tmp_path: Path, reader: str) -> None:
    with pytest.raises(ConfigError, match="readers"):
        _dataset(tmp_path, _view("management"), readers=[reader])


def test_an_arn_reader_is_rendered_as_written(tmp_path: Path) -> None:
    arn = f"arn:aws:iam::{MANAGEMENT}:role/jwall-engineering-braveheart-trainer-task-gpu"
    settings = _view("production", {"braveheart-selfplay": "moving"})
    assert _dataset(tmp_path, settings, readers=[arn])["readers"] == [arn]


# -- the copy -------------------------------------------------------------------


def test_a_moving_projects_old_bucket_lets_the_production_admin_read(tmp_path: Path) -> None:
    moving = {"braveheart-selfplay": "moving"}
    assert _dataset(tmp_path, _view("management", moving), readers=[])["readers"] == [
        PRODUCTION_ADMIN
    ]
    assert _dataset(tmp_path, _view("management"), readers=[])["readers"] == []
    assert _dataset(tmp_path, _view("production", moving), readers=[])["readers"] == []


# -- Databricks -----------------------------------------------------------------


def test_no_share_role_is_named_where_databricks_is_off(tmp_path: Path) -> None:
    from jaws.access import compute_access, load_registry

    handshake = compute_access(
        load_registry(FIXTURES / "datasets"),
        {
            "braveheart-selfplay": load_site_config(
                FIXTURES / "registry" / "braveheart-selfplay.yaml"
            ),
            "braveheart-databricks": load_site_config(
                FIXTURES / "registry" / "braveheart-databricks.yaml"
            ),
        },
    )
    settings = _view("production", {"braveheart-selfplay": "moving"})
    assert settings.databricks is not None and not settings.databricks.enabled
    project = Project.from_config(_selfplay(tmp_path, readers=[]), settings)
    (dataset,) = render_tfvars(project, settings, access=handshake)["datasets"]
    assert dataset["readers"] == []


# -- plans of both stacks ---------------------------------------------------------


def test_a_moving_projects_plan_comment_names_its_account() -> None:
    from jaws.cli import plan_subject

    moving = {"braveheart-selfplay": "moving"}
    assert plan_subject("braveheart-selfplay", _view("management", moving)) == (
        "braveheart-selfplay (management)"
    )
    assert plan_subject("braveheart-selfplay", _view("production", moving)) == (
        "braveheart-selfplay (production)"
    )
    assert plan_subject("braveheart-selfplay", _view("management")) == "braveheart-selfplay"
