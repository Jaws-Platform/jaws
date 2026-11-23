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
    OnboardedProject,
    ProjectGuardrails,
    Settings,
    load_document,
    load_settings,
)
from jaws.site import Site, load_site_config

FIXTURES = Path(__file__).parent / "fixtures"
SITE_FIXTURES = sorted((FIXTURES / "sites").glob("*.yaml"))
REPO_ROOT = Path(__file__).resolve().parent.parent
#: The platform configuration the suite's baseline starts from: a neutral copy of
#: config/'s shape, so no test depends on the owner's own values.
CONFIG_DIR = REPO_ROOT / "tests" / "fixtures" / "platform"
#: The owner's own configuration. Only tests/platform/ reads it.
PLATFORM_CONFIG_DIR = REPO_ROOT / "config"
#: The GitHub owner the suite onboards its sample projects under.
TEST_OWNER = "Test-Fixtures"


def repo_config() -> dict[str, Any]:
    """The repository's tool configuration (config/) as one raw mapping."""
    return load_document(CONFIG_DIR)


def project_entry(config: dict[str, Any], key: str) -> dict[str, Any]:
    """A raw config's entry for project `key`, whichever owner it is under."""
    for group in config["projects"].values():
        if key in group["projects"]:
            entry: dict[str, Any] = group["projects"][key]
            return entry
    raise KeyError(f"project {key!r} is not onboarded")


def onboarded(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A raw config's projects by key."""
    return {k: p for g in config["projects"].values() for k, p in g["projects"].items()}


def onboard(
    config: dict[str, Any],
    key: str,
    guardrails: ProjectGuardrails | None = None,
    *,
    type: str | None = None,
    owner: str = TEST_OWNER,
) -> dict[str, Any]:
    """Onboard `key` in a raw config with `guardrails`, or set an onboarded
    project's guardrails (keeping who it is). Returns the raw entry."""
    approved = guardrails.model_dump(mode="json", exclude_defaults=True) if guardrails else {}
    try:
        entry = project_entry(config, key)
    except KeyError:
        group = config["projects"].setdefault(owner, {"owner_id": "100000", "projects": {}})
        entry = group["projects"].setdefault(key, {})
        entry.update(
            description=f"The suite's {key} sample",
            type=type or ("databricks" if approved.get("databricks") else "research"),
            repository=key,
            repository_id="1",
        )
    else:
        for field in ProjectGuardrails.model_fields:
            entry.pop(field, None)
        if type is not None:
            entry["type"] = type
    entry.update(approved)
    return entry


def offboard(config: dict[str, Any], key: str) -> None:
    """Remove project `key` from a raw config (and its owner, once empty)."""
    for owner, group in list(config["projects"].items()):
        if group["projects"].pop(key, None) is not None:
            if not group["projects"]:
                del config["projects"][owner]
            return
    raise KeyError(f"project {key!r} is not onboarded")


#: The central entry the math-prover sample would have once it is onboarded.
MATH_PROVER_GUARDRAILS = ProjectGuardrails(
    instance_types=("c8a.xlarge", "g6e.xlarge", "g6e.2xlarge", "g6e.4xlarge"),
    task_profiles=("cpu", "train"),
    datasets={
        "jaws-math-prover-artifacts": DatasetRetention(
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
#: datagen and relabel profiles, a dataset). Stated here, not read from config/,
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
    datasets={"jaws-braveheart-nnue": DatasetRetention()},
)


#: The central entry of the databricks-poc sample (fixtures/bots/databricks-poc.yaml),
#: the suite's Databricks workspace project. Stated here, not read from config/,
#: which dropped the real project when it was retired (2026-11-19).
DATABRICKS_POC_GUARDRAILS = ProjectGuardrails(
    databricks=DatabricksProject(
        compute_policies=("small-interactive", "jobs"),
        cost_center="cc-0000",
        vpc_cidr="10.40.0.0/16",
        admins=("owner@example.com",),
    )
)


def fixture_config(path: Path = CONFIG_DIR) -> dict[str, Any]:
    """The tool configuration as the suite's baseline, with the central entries of the
    braveheart and databricks-poc samples and Databricks enabled. The raw mapping a
    test writes out as one config file (the loader reads one file like the directory)."""
    config = load_document(path)
    onboard(config, "braveheart", BRAVEHEART_GUARDRAILS)
    config["databricks"]["enabled"] = True
    onboard(config, "databricks-poc", DATABRICKS_POC_GUARDRAILS, type="databricks")
    return config


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


def with_guardrails(
    settings: Settings, project: str, guardrails: ProjectGuardrails, *, validate: bool = True
) -> Settings:
    """`settings` with `guardrails` as the central entry for `project` (onboarding it
    if it is not). `validate=False` swaps the entry in without validating the result,
    for a check's test that needs a state the loader refuses."""
    if not validate:
        base = settings.projects.get(project)
        onboarding = (
            {
                f: getattr(base, f)
                for f in OnboardedProject.model_fields
                if f not in ProjectGuardrails.model_fields
            }
            if base is not None
            else {
                "description": f"The suite's {project} sample",
                "repository": project,
                "repository_id": "1",
                "type": "databricks" if guardrails.databricks else "research",
            }
        )
        approved = {f: getattr(guardrails, f) for f in ProjectGuardrails.model_fields}
        entry = OnboardedProject.model_construct(**onboarding, **approved)
        copy = settings.model_copy()
        copy._projects = {**settings.projects, project: entry}
        return copy
    raw = settings.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    onboard(raw, project, guardrails)
    return Settings.model_validate(raw)


def replace_projects(
    settings: Settings, projects: dict[str, ProjectGuardrails], **sections: object
) -> Settings:
    """`settings` with exactly `projects` onboarded (each as `onboard` would) and
    any top-level `sections` replaced, such as `databricks=None`."""
    raw = settings.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    raw["projects"] = {}
    for key, guardrails in projects.items():
        onboard(raw, key, guardrails)
    for name, value in sections.items():
        raw[name] = value
    return Settings.model_validate(raw)


def workspace_config(root: Path) -> Path:
    """A workspace's tool configuration: one file in ./config, where the CLI looks."""
    return root / "config" / "config.yaml"


def write_config(root: Path, config: dict[str, Any], *, sort_keys: bool = True) -> Path:
    """Write a raw config as a workspace's tool configuration."""
    path = workspace_config(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=sort_keys))
    return path


def read_config(root: Path) -> dict[str, Any]:
    """A workspace's tool configuration as a raw mapping."""
    return load_document(workspace_config(root))


@pytest.fixture(autouse=True)
def _restore_environment() -> Iterator[None]:
    """Each test gets the environment back as it found it, and starts as an
    owner's shell, not a workflow step: CI sets GITHUB_ACTIONS, GITHUB_OUTPUT
    and the like, and a test that behaved
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
                "bucket_name": {"value": "jaws-guitar-knowledge-base"},
                "prod_url": {"value": "https://guitar.example.com/"},
                "prod_distribution_id": {"value": "E1PROD"},
                "dev_url": {"value": None},
                "dev_distribution_id": {"value": None},
                "preview_url_pattern": {"value": "https://pr-<n>.preview.guitar.example.com"},
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
    """A working directory with the braveheart bot file, its lichess config and the tool config."""
    root = tmp_path / "bot-workspace"
    (root / "lichess").mkdir(parents=True)
    shutil.copy(FIXTURES / "bots" / "braveheart.yaml", root / "jaws.yaml")
    write_config(root, fixture_config(), sort_keys=False)
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
    """A working directory holding the math-prover file and a tool config approving it."""
    root = tmp_path / "research-workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "bots" / "math-prover.yaml", root / "jaws.yaml")
    config = fixture_config()
    onboard(config, "math-prover", MATH_PROVER_GUARDRAILS, type="research")
    write_config(root, config)
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory holding the guitar site file and the tool config."""
    root = tmp_path / "workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "sites" / "guitar-knowledge-base.yaml", root / "jaws.yaml")
    write_config(root, fixture_config(), sort_keys=False)
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root


@pytest.fixture
def databricks_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A working directory with the databricks-poc file and a tool config enabling the account."""
    root = tmp_path / "databricks-workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "bots" / "databricks-poc.yaml", root / "jaws.yaml")
    config = fixture_config()
    config["databricks"]["enabled"] = True
    config["databricks"]["account_id"] = "11111111-1111-1111-1111-111111111111"
    config["databricks"]["client_id"] = "22222222-2222-2222-2222-222222222222"
    # Enabled settings refuse the placeholder metastore admin (as the foundation plan does).
    config["databricks"]["metastore_admins"] = ["owner@jwall-engineering.test"]
    write_config(root, config)
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    yield root
