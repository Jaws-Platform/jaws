"""Shared datasets: config.yaml approves a dataset bucket's `databricks_share`, the
producer's dataset component consents by listing the same `consumers`, the
foundation registers one read-only location through the host, the producer's
bucket policy names the share role, and each consumer's endpoint lets it in."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from jwall_engineering_sites import guardrails
from jwall_engineering_sites.errors import ConfigError
from jwall_engineering_sites.project import Project
from jwall_engineering_sites.settings import Settings, load_settings, share_role_name
from jwall_engineering_sites.site import load_site_config
from jwall_engineering_sites.stack import _bot_tfvars, _read_only_datasets

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent
NNUE = "jwall-engineering-braveheart-nnue"
NNUE_ROLE = "arn:aws:iam::650503560686:role/jwall-engineering-braveheart-nnue-databricks-share"


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((FIXTURES / "config.yaml").read_text())
    return raw


def _load(tmp_path: Path, raw: dict[str, Any]) -> Settings:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_settings(path, environ={})


def _share(raw: dict[str, Any]) -> dict[str, Any]:
    share: dict[str, Any] = raw["projects"]["braveheart"]["datasets"][NNUE]["databricks_share"]
    return share


def _bot_file(tmp_path: Path, consumers: list[str] | None, prefix: str = "data/") -> Path:
    data: dict[str, Any] = yaml.safe_load((FIXTURES / "bots" / "braveheart.yaml").read_text())
    dataset = next(c for c in data["components"] if c["kind"] == "dataset")
    dataset["prefix"] = prefix
    if consumers is not None:
        dataset["consumers"] = consumers
    path = tmp_path / "jwall-engineering-sites.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


# --- config.yaml ------------------------------------------------------------


def test_the_nnue_share_is_approved_for_braveheart_databricks(settings: Settings) -> None:
    (share,) = settings.databricks_shares()
    assert share.producer == "braveheart"
    assert share.bucket == NNUE
    assert share.name == "braveheart-nnue"
    assert share.prefix == "data/"
    assert share.consumers == ("braveheart-databricks",)
    assert share.role_arn == NNUE_ROLE


def test_a_consumer_must_be_a_databricks_workspace_project(tmp_path: Path) -> None:
    raw = _raw()
    _share(raw)["consumers"] = ["braveheart-databricks", "braveheart"]
    with pytest.raises(ConfigError, match=r"braveheart.*not a Databricks workspace project"):
        _load(tmp_path, raw)


def test_consumers_must_not_repeat(tmp_path: Path) -> None:
    raw = _raw()
    _share(raw)["consumers"] = ["braveheart-databricks", "braveheart-databricks"]
    with pytest.raises(ConfigError, match="must not repeat"):
        _load(tmp_path, raw)


def test_a_share_needs_a_consumer(tmp_path: Path) -> None:
    raw = _raw()
    _share(raw)["consumers"] = []
    with pytest.raises(ConfigError, match="consumers"):
        _load(tmp_path, raw)


def test_a_share_prefix_is_a_prefix(tmp_path: Path) -> None:
    raw = _raw()
    _share(raw)["prefix"] = "/data/"
    with pytest.raises(ConfigError, match=r"prefix|sub-prefix"):
        _load(tmp_path, raw)


def test_consumers_are_sorted(tmp_path: Path) -> None:
    raw = _raw()
    _share(raw)["consumers"] = ["databricks-poc", "braveheart-databricks"]
    (share,) = _load(tmp_path, raw).databricks_shares()
    assert share.consumers == ("braveheart-databricks", "databricks-poc")


def test_share_role_fits_iam() -> None:
    assert len(share_role_name("jwall-engineering", NNUE)) <= 64
    assert (
        share_role_name("jwall-engineering", NNUE)
        == "jwall-engineering-braveheart-nnue-databricks-share"
    )


# --- the producer's consent ---------------------------------------------------


def test_producer_listing_the_approved_consumers_passes(tmp_path: Path, settings: Settings) -> None:
    config = load_site_config(_bot_file(tmp_path, ["braveheart-databricks"]))
    assert guardrails.check(config, settings) == []


def test_producer_listing_nobody_yet_passes(tmp_path: Path, settings: Settings) -> None:
    # Approved centrally but not consented: the location exists, nothing can read.
    config = load_site_config(_bot_file(tmp_path, None))
    assert guardrails.check(config, settings) == []


def test_producer_listing_other_consumers_fails(tmp_path: Path, settings: Settings) -> None:
    config = load_site_config(_bot_file(tmp_path, ["databricks-poc"]))
    problems = guardrails.check(config, settings)
    assert any(
        "consumers ['databricks-poc'] must equal the ['braveheart-databricks']" in p
        for p in problems
    )


def test_producer_listing_a_subset_fails(tmp_path: Path) -> None:
    # One role reads for every consumer, so a subset would still let the rest in.
    raw = _raw()
    _share(raw)["consumers"] = ["braveheart-databricks", "databricks-poc"]
    settings = _load(tmp_path, raw)
    config = load_site_config(_bot_file(tmp_path, ["braveheart-databricks"]))
    assert any("must equal" in p for p in guardrails.check(config, settings))


def test_producer_sharing_an_unapproved_dataset_fails(tmp_path: Path) -> None:
    raw = _raw()
    del raw["projects"]["braveheart"]["datasets"][NNUE]["databricks_share"]
    settings = _load(tmp_path, raw)
    config = load_site_config(_bot_file(tmp_path, ["braveheart-databricks"]))
    assert any("approved in config.yaml" in p for p in guardrails.check(config, settings))


def test_producer_prefix_must_match_the_share(tmp_path: Path, settings: Settings) -> None:
    config = load_site_config(_bot_file(tmp_path, ["braveheart-databricks"], prefix="other/"))
    assert any("databricks_share.prefix" in p for p in guardrails.check(config, settings))


# --- what the stacks get ------------------------------------------------------


def test_consenting_producer_names_the_share_role_as_a_reader(
    tmp_path: Path, settings: Settings
) -> None:
    project = Project.from_config(
        load_site_config(_bot_file(tmp_path, ["braveheart-databricks"])), settings
    )
    (dataset,) = _bot_tfvars(project, settings)["datasets"]
    assert dataset["readers"] == [NNUE_ROLE]


def test_not_yet_consenting_producer_names_no_reader(tmp_path: Path, settings: Settings) -> None:
    project = Project.from_config(load_site_config(_bot_file(tmp_path, None)), settings)
    (dataset,) = _bot_tfvars(project, settings)["datasets"]
    assert dataset["readers"] == []


def test_the_consumer_endpoint_gets_the_share(settings: Settings) -> None:
    assert _read_only_datasets("braveheart-databricks", settings) == {
        "braveheart-nnue": {"bucket": NNUE, "prefix": "data/", "role_arn": NNUE_ROLE}
    }


def test_other_workspaces_get_nothing(settings: Settings) -> None:
    assert _read_only_datasets("databricks-poc", settings) == {}


# --- the foundation derives the same names -------------------------------------


def test_foundation_names_shares_as_settings_does() -> None:
    text = (REPO_ROOT / "foundation" / "databricks.tf").read_text()
    # share_name: the bucket without "<organization>-"; the module adds -databricks-share.
    assert 'name      = trimprefix(bucket, "${local.context.organization}-")' in text
    assert "name_root         = local.context.organization" in text
    assert re.search(r"users_group_name = \"\$\{c\}-workspace-users\"", text)
    assert '"${c}-prod"' in text  # workspaces are <project>-prod


def test_foundation_shares_through_the_host_provider() -> None:
    text = (REPO_ROOT / "foundation" / "databricks.tf").read_text()
    block = text[text.index('module "databricks_shared_dataset"') :]
    assert "providers = { aws = aws, databricks = databricks.shared }" in block
    providers = (REPO_ROOT / "foundation" / "providers.tf").read_text()
    assert 'alias     = "shared"' in providers
    assert "module.databricks_shared_host[0].workspace_url" in providers
