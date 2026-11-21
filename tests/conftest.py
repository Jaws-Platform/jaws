from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from jaws.project import Project
from jaws.settings import (
    DatabricksProject,
    DatasetRetention,
    ProjectGuardrails,
    Settings,
    load_settings,
)
from jaws.site import Site, load_site_config

FIXTURES = Path(__file__).parent / "fixtures"
SITE_FIXTURES = sorted((FIXTURES / "sites").glob("*.yaml"))
REPO_ROOT = Path(__file__).resolve().parent.parent


#: The central entry the math-prover sample would have once it is onboarded.
MATH_PROVER_GUARDRAILS = ProjectGuardrails(
    instance_types=("c8a.xlarge", "g6e.xlarge", "g6e.2xlarge", "g6e.4xlarge"),
    task_profiles=("cpu", "train"),
    datasets={
        "jwall-engineering-math-prover-artifacts": DatasetRetention(
            prefix="data/",
            versioning=True,
            expire_noncurrent_days=90,
            expire_prefixes={"tmp/": 30},
            write_once=("runs/", "models/"),
        )
    },
)


#: The central entry the braveheart sample (fixtures/bots/braveheart.yaml) needs: the
#: engine as it was before the split, the suite's full-featured project (GPU,
#: datagen and relabel profiles, a dataset). Stated here, not read from config.yaml,
#: whose entry for the real engine shrank at the split's cutover.
BRAVEHEART_GUARDRAILS = ProjectGuardrails(
    instance_types=(
        "c8a.xlarge",
        "c8a.8xlarge",
        "c8a.16xlarge",
        "g6.xlarge",
        "g6.2xlarge",
        "g6e.xlarge",
    ),
    task_profiles=("cpu", "gpu", "sprt", "match", "datagen", "relabel"),
    datasets={"jwall-engineering-braveheart-nnue": DatasetRetention()},
)


#: The central entry of the databricks-poc sample (fixtures/bots/databricks-poc.yaml),
#: the suite's Databricks workspace project. Stated here, not read from config.yaml,
#: which dropped the real project when it was retired (2026-11-19).
DATABRICKS_POC_GUARDRAILS = ProjectGuardrails(
    databricks=DatabricksProject(
        compute_policies=("small-interactive", "jobs"),
        cost_center="cc-0000",
        vpc_cidr="10.40.0.0/16",
        admins=("jimmy.wallace145@gmail.com",),
    )
)


def databricks_in_management(config: dict[str, Any]) -> dict[str, Any]:
    """`config` with Databricks enabled in the management account, as the suite's
    Databricks tests expect: their samples (databricks-poc, braveheart-databricks)
    live there. Stated here, not read from config.yaml, which flips Databricks
    between the accounts when it moves (docs/databricks.md, "One account at a time").
    A test about production says so itself."""
    config["databricks"]["enabled"] = True
    overrides = config["production"]["overrides"].setdefault("databricks", {})
    overrides["enabled"] = False
    config["production"]["projects"].pop("braveheart-databricks", None)
    config["projects"]["databricks-poc"] = DATABRICKS_POC_GUARDRAILS.model_dump(
        mode="json", exclude_defaults=True
    )
    return config


def fixture_config(path: Path = FIXTURES / "config.yaml") -> dict[str, Any]:
    """config.yaml's fixture copy as the suite's baseline: the braveheart sample's
    central entry, in the management account, and Databricks in the management
    account with the databricks-poc sample. The raw mapping a test writes out as a
    config.yaml. The sample stays in management whatever config.yaml says of the
    real engine's move; a test about production says so itself."""
    config: dict[str, Any] = yaml.safe_load(path.read_text())
    config["projects"]["braveheart"] = BRAVEHEART_GUARDRAILS.model_dump(mode="json")
    config["production"]["projects"].pop("braveheart", None)
    # The baseline has the management account in use, so a test can keep a
    # project there; a test about its retirement says so itself.
    config["production"].pop("management_retired", None)
    return databricks_in_management(config)


_BASELINE: dict[str, Path] = {}


def baseline_config_path() -> Path:
    """fixture_config() written once per session, for load_settings."""
    if "path" not in _BASELINE:
        directory = Path(tempfile.mkdtemp(prefix="jaws-baseline-"))
        path = directory / "config.yaml"
        path.write_text(yaml.safe_dump(fixture_config(), sort_keys=False))
        _BASELINE["path"] = path
    return _BASELINE["path"]


def fixture_settings(path: Path | None = None, **kwargs: object) -> Settings:
    """The suite's baseline settings (fixture_config()), or another file's."""
    return load_settings(path or baseline_config_path(), **kwargs)  # type: ignore[arg-type]


def management_only(settings: Settings, *projects: str) -> Settings:
    """`settings` with `projects` taken out of production.projects: a test about a
    project's own behaviour states that it isn't moving, rather than inheriting
    whatever config.yaml says today (which changes with every move)."""
    assert settings.production is not None
    remaining = {k: v for k, v in settings.production.projects.items() if k not in projects}
    production = settings.production.model_copy(
        update={"projects": remaining, "management_retired": False}
    )
    return settings.model_copy(update={"production": production})


def with_guardrails(settings: Settings, project: str, guardrails: ProjectGuardrails) -> Settings:
    """`settings` with `guardrails` as the central entry for `project`."""
    return settings.model_copy(update={"projects": {**settings.projects, project: guardrails}})


@pytest.fixture(autouse=True)
def _restore_environment() -> Iterator[None]:
    """Each test gets the environment back as it found it. A command adopts the old
    JES_* variables by writing os.environ (jaws.legacy), which monkeypatch does not
    undo, so without this a JES_CONFIG set by one test chose the next test's config.

    It also starts every test as an owner's shell, not a workflow step: CI sets
    GITHUB_ACTIONS, GITHUB_OUTPUT and the like, and a test that behaved
    differently there passed locally and failed in CI (2026-11-19). A test about
    a workflow step sets the variables it needs itself."""
    with patch.dict(os.environ):
        for name in [k for k in os.environ if k == "CI" or k.startswith(("GITHUB_", "RUNNER_"))]:
            del os.environ[name]
        yield


@pytest.fixture
def settings() -> Settings:
    return fixture_settings(environ={})


@pytest.fixture(params=SITE_FIXTURES, ids=[p.stem for p in SITE_FIXTURES])
def site(request: pytest.FixtureRequest, settings: Settings) -> Site:
    return Site.from_config(load_site_config(request.param), settings)


@pytest.fixture
def guitar(settings: Settings) -> Site:
    return Site.from_config(
        load_site_config(FIXTURES / "sites" / "guitar-knowledge-base.yaml"), settings
    )


@pytest.fixture
def bot(settings: Settings) -> Project:
    return Project.from_config(load_site_config(FIXTURES / "bots" / "braveheart.yaml"), settings)


@pytest.fixture
def research(settings: Settings) -> Project:
    """The math-prover sample: a dataset and a task-runner, no bot, with its central entry."""
    return Project.from_config(
        load_site_config(FIXTURES / "bots" / "math-prover.yaml"),
        with_guardrails(settings, "math-prover", MATH_PROVER_GUARDRAILS),
    )


@pytest.fixture
def logger() -> logging.Logger:
    log = logging.getLogger("test-jaws")
    log.setLevel(logging.DEBUG)
    return log


@pytest.fixture
def fake_terraform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put the fake terraform first on PATH; returns its invocation log."""
    log = tmp_path / "terraform.log"
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "bucket_name": {"value": "jwall-engineering-guitar-knowledge-base"},
                "prod_url": {"value": "https://guitar.jwall.engineering/"},
                "prod_distribution_id": {"value": "E1PROD"},
                "dev_url": {"value": None},
                "dev_distribution_id": {"value": None},
                "preview_url_pattern": {"value": "https://pr-<n>.preview.guitar.jwall.engineering"},
                "preview_distribution_id": {"value": "E1PREVIEW"},
            }
        )
    )
    monkeypatch.setenv("PATH", f"{FIXTURES / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_TF_LOG", str(log))
    monkeypatch.setenv("FAKE_TF_OUTPUTS", str(outputs))
    monkeypatch.delenv("JAWS_STACK_DIR", raising=False)
    monkeypatch.setenv("JAWS_STACKS_ROOT", str(REPO_ROOT / "stacks"))
    monkeypatch.setenv("FAKE_TF_TFVARS", str(tmp_path / "rendered.tfvars.json"))
    monkeypatch.setenv("JAWS_PLUGIN_DIR", "")
    return log


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put the fake docker first on PATH; returns its invocation log."""
    log = tmp_path / "docker.log"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{FIXTURES / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    return log


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A small built site."""
    root = tmp_path / "dist"
    (root / "_astro").mkdir(parents=True)
    (root / "index.html").write_text("<h1>home</h1>")
    (root / "about.html").write_text("<h1>about</h1>")
    (root / "_astro" / "app.abc123.js").write_text("console.log(1)")
    (root / "robots.txt").write_text("User-agent: *")
    return root


@pytest.fixture
def bot_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory holding the braveheart bot file, its lichess config and config.yaml."""
    root = tmp_path / "bot-workspace"
    (root / "lichess").mkdir(parents=True)
    shutil.copy(FIXTURES / "bots" / "braveheart.yaml", root / "jaws.yaml")
    (root / "config.yaml").write_text(yaml.safe_dump(fixture_config(), sort_keys=False))
    (root / "lichess" / "config.yml").write_text(
        "token: LICHESS_TOKEN_PLACEHOLDER\nurl: https://lichess.org/\n"
        "engine:\n  dir: ./engines/\n  name: braveheart\n  protocol: uci\n"
        "  uci_options:\n    Hash: 16\n"
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root


@pytest.fixture
def research_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory holding the math-prover file and a config.yaml approving it."""
    root = tmp_path / "research-workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "bots" / "math-prover.yaml", root / "jaws.yaml")
    config = fixture_config()
    config["projects"]["math-prover"] = MATH_PROVER_GUARDRAILS.model_dump(mode="json")
    (root / "config.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory holding the guitar site file and config.yaml, with the
    site in the management account only: these tests are about a site's own
    commands, and must not change account on the pull request that moves it."""
    root = tmp_path / "workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "sites" / "guitar-knowledge-base.yaml", root / "jaws.yaml")
    config = fixture_config()
    config["production"]["projects"].pop("guitar-knowledge-base", None)
    (root / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root


@pytest.fixture
def databricks_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory with the databricks-poc file and a config.yaml enabling the account."""
    root = tmp_path / "databricks-workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "bots" / "databricks-poc.yaml", root / "jaws.yaml")
    config = fixture_config()
    config["databricks"]["enabled"] = True
    config["databricks"]["account_id"] = "11111111-1111-1111-1111-111111111111"
    config["databricks"]["client_id"] = "22222222-2222-2222-2222-222222222222"
    # Enabled settings refuse the placeholder metastore admin (as the foundation plan does).
    config["databricks"]["metastore_admins"] = ["owner@jwall-engineering.test"]
    (root / "config.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root
