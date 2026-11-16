"""The reconcile's inputs: every onboarded dataset and the consumers bound to it.

`access render` reads the registry and every Databricks workspace project's and
dataset owner's file, then writes data-access/'s tfvars and a summary. A file
that cannot be read, or a registry that offboards a dataset still named by a
handshake, writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from jwall_engineering_sites import cli
from jwall_engineering_sites.access import (
    access_summary,
    compute_access,
    data_access_tfvars,
    fingerprint,
    load_registry,
)
from jwall_engineering_sites.errors import ConfigError
from jwall_engineering_sites.settings import Settings
from jwall_engineering_sites.site import load_site_config
from tests.conftest import FIXTURES
from tests.test_cli import runner

HOST = "https://dbc-01234567-89ab.cloud.databricks.com"
PURPOSE = "generation-over-generation self-play analysis"


def _with_host(settings: Settings, url: str | None = HOST) -> Settings:
    assert settings.databricks is not None
    return settings.model_copy(
        update={"databricks": settings.databricks.model_copy(update={"shared_host_url": url})}
    )


def _files(consumer_purpose: str = PURPOSE) -> dict[str, Any]:
    consumer = load_site_config(FIXTURES / "registry" / "braveheart-databricks.yaml")
    workspace = consumer.components[0]
    read = workspace.reads[0].model_copy(update={"purpose": consumer_purpose})  # type: ignore[union-attr]
    consumer = consumer.model_copy(
        update={"components": [workspace.model_copy(update={"reads": (read,)})]}
    )
    return {
        "braveheart-selfplay": load_site_config(FIXTURES / "registry" / "braveheart-selfplay.yaml"),
        "braveheart-databricks": consumer,
    }


def _expected_without_fingerprint() -> dict[str, Any]:
    return {
        "host_workspace_url": HOST,
        "datasets": {
            "braveheart-selfplay-positions": {
                "id": "braveheart-selfplay/positions",
                "location_name": "jwall-engineering-ds-braveheart-selfplay-positions",
                "consumers": {
                    "braveheart-databricks": {
                        "users_group_name": "braveheart-databricks-workspace-users",
                        "purpose": PURPOSE,
                    }
                },
            }
        },
    }


def test_the_tfvars_bind_each_agreed_consumer(settings: Settings) -> None:
    registry = load_registry(FIXTURES / "datasets")
    tfvars = data_access_tfvars(compute_access(registry, _files()), registry, _with_host(settings))
    expected = _expected_without_fingerprint()
    # The fingerprint, derived here independently: the canonical JSON's SHA-256.
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert tfvars == expected | {"fingerprint": hashlib.sha256(canonical.encode()).hexdigest()}


def test_an_onboarded_dataset_nobody_reads_has_no_consumers(settings: Settings) -> None:
    registry = load_registry(FIXTURES / "datasets")
    tfvars = data_access_tfvars(compute_access(registry, {}), registry, _with_host(settings))
    assert tfvars["datasets"]["braveheart-selfplay-positions"]["consumers"] == {}


def test_the_fingerprint_is_stable_under_key_order() -> None:
    ordered = {"host_workspace_url": HOST, "datasets": {"k": {"id": "o/k", "consumers": {}}}}
    shuffled = {"datasets": {"k": {"consumers": {}, "id": "o/k"}}, "host_workspace_url": HOST}
    canonical = '{"datasets":{"k":{"consumers":{},"id":"o/k"}},"host_workspace_url":"' + HOST + '"}'
    assert fingerprint(ordered) == fingerprint(shuffled)
    assert fingerprint(ordered) == hashlib.sha256(canonical.encode()).hexdigest()


def test_the_fingerprint_changes_with_a_purpose(settings: Settings) -> None:
    registry = load_registry(FIXTURES / "datasets")
    host = _with_host(settings)
    once = data_access_tfvars(compute_access(registry, _files()), registry, host)["fingerprint"]
    again = data_access_tfvars(compute_access(registry, _files()), registry, host)["fingerprint"]
    other = data_access_tfvars(compute_access(registry, _files("another purpose")), registry, host)[
        "fingerprint"
    ]
    assert once == again != other


def test_the_tfvars_need_the_shared_host_url(settings: Settings) -> None:
    registry = load_registry(FIXTURES / "datasets")
    with pytest.raises(ConfigError, match="shared_host_url"):
        data_access_tfvars(compute_access(registry, _files()), registry, _with_host(settings, None))


def test_the_summary_lists_edges_and_pending_reasons() -> None:
    registry = load_registry(FIXTURES / "datasets")
    summary = access_summary(compute_access(registry, _files()))
    assert "braveheart-selfplay/positions" in summary and "braveheart-databricks" in summary
    files = _files()
    workspace = files["braveheart-databricks"].components[0]
    files["braveheart-databricks"] = files["braveheart-databricks"].model_copy(
        update={"components": [workspace.model_copy(update={"reads": ()})]}
    )
    pending = access_summary(compute_access(registry, files))
    assert "the consumer does not read the dataset" in pending


# -- the command -------------------------------------------------------------------


@pytest.fixture
def render_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An infra checkout's datasets/ and config.yaml, and a directory of project files."""
    root = tmp_path / "infra"
    shutil.copytree(FIXTURES / "datasets", root / "datasets")
    config = yaml.safe_load((FIXTURES / "config.yaml").read_text())
    config["databricks"]["shared_host_url"] = HOST
    (root / "config.yaml").write_text(yaml.safe_dump(config))
    files = tmp_path / "project-files"
    files.mkdir()
    for name in ("braveheart-selfplay", "braveheart-databricks", "databricks-poc"):
        source = FIXTURES / "registry" / f"{name}.yaml"
        if not source.exists():
            source = FIXTURES / "bots" / f"{name}.yaml"
        if source.exists():
            shutil.copy(source, files / f"{name}.yaml")
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("JES_INFRA_ROOT", raising=False)
    monkeypatch.setenv("JES_PROJECT_FILES_DIR", str(files))
    yield root


def test_render_writes_the_tfvars_and_the_summary(render_workspace: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["access", "render", "--out", str(out)])
    assert result.exit_code == 0, result.output
    tfvars = json.loads((out / "terraform.tfvars.json").read_text())
    consumers = tfvars["datasets"]["braveheart-selfplay-positions"]["consumers"]
    assert list(consumers) == ["braveheart-databricks"]
    assert "braveheart-databricks" in (out / "access-summary.md").read_text()


def test_a_read_naming_an_unregistered_project_is_pending_not_an_error(
    render_workspace: Path, tmp_path: Path
) -> None:
    """One consumer's merged typo must not stop every sweep, and so every
    revocation: with no producer file to agree, it grants nothing and is
    reported."""
    path = tmp_path / "project-files" / "braveheart-databricks.yaml"
    data = yaml.safe_load(path.read_text())
    workspace = next(c for c in data["components"] if c["kind"] == "databricks-workspace")
    workspace["reads"].append({"dataset": "braveheart-selfply/positions", "purpose": "a typo"})
    path.write_text(yaml.safe_dump(data))
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["access", "render", "--out", str(out)])
    assert result.exit_code == 0, result.output
    tfvars = json.loads((out / "terraform.tfvars.json").read_text())
    consumers = tfvars["datasets"]["braveheart-selfplay-positions"]["consumers"]
    assert list(consumers) == ["braveheart-databricks"]
    summary = (out / "access-summary.md").read_text()
    assert (
        "| `braveheart-selfply/positions` | `braveheart-selfply` | `braveheart-databricks` |"
        in summary
    )
    assert "the producer is not a registered project" in summary


def test_render_with_a_failing_fetch_writes_nothing(render_workspace: Path, tmp_path: Path) -> None:
    (tmp_path / "project-files" / "braveheart-databricks.yaml").unlink()
    out = tmp_path / "out"
    result = runner.invoke(cli.app, ["access", "render", "--out", str(out)])
    assert result.exit_code == 2, result.output
    assert not (out / "terraform.tfvars.json").exists()
    assert not (out / "access-summary.md").exists()


def test_render_refuses_offboarding_a_dataset_a_handshake_still_names(
    render_workspace: Path, tmp_path: Path
) -> None:
    base = tmp_path / "base-datasets"
    shutil.copytree(render_workspace / "datasets", base)
    shutil.rmtree(render_workspace / "datasets" / "braveheart-selfplay")
    out = tmp_path / "out"
    result = runner.invoke(
        cli.app, ["access", "render", "--out", str(out), "--base-registry", str(base)]
    )
    assert result.exit_code == 2, result.output
    log = (
        render_workspace / ".jwall-engineering-sites" / "jwall-engineering-sites.log"
    ).read_text()
    assert "offboarding braveheart-selfplay/positions" in log
    assert not (out / "terraform.tfvars.json").exists()

    # Once both halves are gone, the offboarding goes through.
    for name, kind, field in (
        ("braveheart-selfplay", "dataset", "consumers"),
        ("braveheart-databricks", "databricks-workspace", "reads"),
    ):
        path = tmp_path / "project-files" / f"{name}.yaml"
        data = yaml.safe_load(path.read_text())
        next(c for c in data["components"] if c["kind"] == kind).pop(field, None)
        path.write_text(yaml.safe_dump(data))
    result = runner.invoke(
        cli.app, ["access", "render", "--out", str(out), "--base-registry", str(base)]
    )
    assert result.exit_code == 0, result.output
