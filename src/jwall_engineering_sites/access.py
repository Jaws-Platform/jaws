"""Onboarded datasets and the handshakes that grant read access to them.

A dataset is onboarded once, centrally, by one file in this repository,
`datasets/<owner>/<name>.yaml`: the foundation creates its one read-only,
platform-owned role, storage credential and external location, named
`<organization>-ds-<owner>-<name>`. Onboarding grants nothing. A Databricks
workspace reads a dataset only while the producing project lists it under the
dataset's `consumers` and the consuming project lists the dataset under its
workspace's `reads`: a handshake (docs/databricks.md, "Datasets and access").
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .components import DatabricksWorkspace, Dataset, check_prefixes
from .errors import ConfigError
from .settings import default_config_path
from .site import SITE_FILE, SiteConfig, load_site_config, site_config_from_text

#: The longest `<owner>-<name>`: the key of the consumer endpoint's
#: `read_only_datasets` (databricks-workspace), stricter than IAM's 43
#: characters under `<organization>-ds-`.
ONBOARDING_KEY_MAX = 40
#: The infra checkout the registry and the project registries are read from.
ENV_INFRA_ROOT = "JES_INFRA_ROOT"
#: The one file in datasets/ that is not a dataset.
REGISTRY_README = "README.md"
#: A directory of `<project>.yaml` read instead of GitHub (tests, local runs).
ENV_PROJECT_FILES_DIR = "JES_PROJECT_FILES_DIR"
#: The registries of projects and their repositories, one line per entry, as
#: the workflows read them (bot-apply.yml, scripts/databricks-projects.sh).
PROJECT_REGISTRIES = (
    ("foundation/bots.tf", "bots"),
    ("foundation/databricks.tf", "databricks_projects"),
)
GITHUB_API = "https://api.github.com"
#: Seconds before a GitHub request gives up. No retries: a failed sweep runs again.
FETCH_TIMEOUT = 20
_REGISTRY_ENTRY = re.compile(r'^ *([a-z0-9-]+) *= *\{ *repository *= *"([^"]*)"')

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FIELDS = ("description", "prefix")


@dataclass(frozen=True)
class OnboardedDataset:
    """One onboarded dataset: a registered project's `dataset` component."""

    owner: str
    name: str
    prefix: str
    description: str

    @property
    def id(self) -> str:
        """`<owner>/<name>`, what consumers list under `reads`."""
        return f"{self.owner}/{self.name}"

    @property
    def key(self) -> str:
        """`<owner>-<name>`: the endpoint key and the platform name's suffix."""
        return f"{self.owner}-{self.name}"

    def bucket(self, organization: str) -> str:
        """The owner's dataset bucket, `<organization>-<owner>-<name>`."""
        return f"{organization}-{self.key}"

    def platform_name(self, organization: str) -> str:
        """The role, storage credential and external location, `<organization>-ds-<key>`."""
        return f"{organization}-ds-{self.key}"

    def role_arn(self, account_id: str, organization: str) -> str:
        return f"arn:aws:iam::{account_id}:role/{self.platform_name(organization)}"

    def url(self, organization: str) -> str:
        """The location's URL, without the trailing slash Databricks drops."""
        return f"s3://{self.bucket(organization)}/{self.prefix.removesuffix('/')}"

    def as_dict(self, organization: str) -> dict[str, str]:
        """Every derived value, as the foundation's registry module outputs it."""
        return {
            "id": self.id,
            "owner": self.owner,
            "name": self.name,
            "prefix": self.prefix,
            "description": self.description,
            "platform_name": self.platform_name(organization),
            "bucket": self.bucket(organization),
            "url": self.url(organization),
        }


def infra_root() -> Path:
    """The infra checkout: JES_INFRA_ROOT, else the directory of config.yaml."""
    if ENV_INFRA_ROOT in os.environ:
        return Path(os.environ[ENV_INFRA_ROOT])
    return default_config_path().parent


def load_registry(directory: Path) -> tuple[OnboardedDataset, ...]:
    """Every onboarded dataset under `directory`, sorted by id.

    A missing directory is an empty registry. Anything else that is not
    `<owner>/<name>.yaml` with exactly `description` and `prefix`, or the
    README, is refused with its path.
    """
    if not directory.is_dir():
        return ()
    datasets: list[OnboardedDataset] = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        if rel == REGISTRY_README:
            continue
        datasets.append(_load_file(path, rel))
    _check_keys(datasets)
    return tuple(sorted(datasets, key=lambda d: d.id))


def _load_file(path: Path, rel: str) -> OnboardedDataset:
    parts = rel.split("/")
    if len(parts) != 2 or not parts[1].endswith(".yaml"):
        raise ConfigError(
            f"datasets/{rel}: a dataset is datasets/<owner>/<name>.yaml (and README.md the "
            "only other file)"
        )
    owner, name = parts[0], parts[1].removesuffix(".yaml")
    for what, value in (("owner", owner), ("name", name)):
        if not _KEBAB.match(value):
            raise ConfigError(f"datasets/{rel}: the {what} {value!r} must be kebab-case")
    key = f"{owner}-{name}"
    if len(key) > ONBOARDING_KEY_MAX:
        raise ConfigError(
            f"datasets/{rel}: <owner>-<name> is {len(key)} characters, more than "
            f"{ONBOARDING_KEY_MAX} (the consumer endpoint's key limit)"
        )
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"datasets/{rel}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict) or sorted(raw) != sorted(_FIELDS):
        found = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise ConfigError(
            f"datasets/{rel}: needs exactly the keys {', '.join(_FIELDS)}, found {found}"
        )
    description, prefix = raw["description"], raw["prefix"]
    if not isinstance(description, str) or not description.strip():
        raise ConfigError(f"datasets/{rel}: description must be a non-empty string")
    if not isinstance(prefix, str):
        raise ConfigError(f"datasets/{rel}: prefix must be a string such as data/")
    try:
        check_prefixes((prefix,))
    except ValueError as exc:
        raise ConfigError(f"datasets/{rel}: prefix {exc}") from exc
    return OnboardedDataset(owner=owner, name=name, prefix=prefix, description=description)


def _check_keys(datasets: list[OnboardedDataset]) -> None:
    """Two ids can share a key (a-b/c and a/b-c), and so a role name: refuse it."""
    by_key: dict[str, list[str]] = {}
    for d in datasets:
        by_key.setdefault(d.key, []).append(d.id)
    clashes = {key: ids for key, ids in by_key.items() if len(ids) > 1}
    if clashes:
        detail = "; ".join(
            f"{key}: {', '.join(sorted(ids))}" for key, ids in sorted(clashes.items())
        )
        raise ConfigError(f"datasets: ids that share a platform name: {detail}")


# -- other projects' files ------------------------------------------------------


def project_repositories(infra_root: Path) -> dict[str, str]:
    """Every registered project and its repository, from foundation/bots.tf and databricks.tf."""
    repositories: dict[str, str] = {}
    for rel, block in PROJECT_REGISTRIES:
        path = infra_root / rel
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError as exc:
            raise ConfigError(f"{path}: the project registry is missing") from exc
        try:
            start = lines.index(f"  {block} = {{")
        except ValueError as exc:
            raise ConfigError(f"{path}: no multi-line `{block} = {{ ... }}` block") from exc
        for line in lines[start + 1 :]:
            if line.startswith("  }"):
                break
            match = _REGISTRY_ENTRY.match(line)
            if match:
                repositories[match.group(1)] = match.group(2)
    return repositories


class ProjectFiles(Protocol):
    """Where another project's jwall-engineering-sites.yaml is read from."""

    def load(self, project: str) -> SiteConfig: ...


@dataclass
class DirectoryProjectFiles:
    """`<directory>/<project>.yaml`: the test fixtures, or a local copy."""

    directory: Path

    def load(self, project: str) -> SiteConfig:
        path = self.directory / f"{project}.yaml"
        if not path.is_file():
            raise ConfigError(f"{project}: no project file at {path}")
        return load_site_config(path)


@dataclass
class GitHubProjectFiles:
    """Each project's file on its repository's default branch, through GitHub's API.

    Every failure names the project and the URL: a file that cannot be read
    is never taken for one without a handshake.
    """

    repositories: Mapping[str, str]
    token: str | None
    opener: Callable[..., Any] = urllib.request.urlopen
    #: The blob SHA of each file read, by project.
    shas: dict[str, str] = field(default_factory=dict)

    def load(self, project: str) -> SiteConfig:
        repository = self.repositories.get(project)
        if repository is None:
            raise ConfigError(
                f"{project}: not a registered project (foundation/bots.tf or "
                "foundation/databricks.tf), so its file cannot be read"
            )
        url = f"{GITHUB_API}/repos/{repository}/contents/{SITE_FILE.name}"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener(request, timeout=FETCH_TIMEOUT) as response:
                payload = json.load(response)
            text = base64.b64decode(payload["content"]).decode()
            sha = str(payload["sha"])
        except (
            urllib.error.URLError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            binascii.Error,
        ) as exc:
            raise ConfigError(f"{project}: could not read {url}: {exc}") from exc
        config = site_config_from_text(text, f"{project} ({url})")
        self.shas[project] = sha
        return config


def project_files_from_env(infra_root: Path) -> ProjectFiles:
    """JES_PROJECT_FILES_DIR when set, else GitHub, with GH_TOKEN or GITHUB_TOKEN if present."""
    if ENV_PROJECT_FILES_DIR in os.environ:
        return DirectoryProjectFiles(Path(os.environ[ENV_PROJECT_FILES_DIR]))
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None
    return GitHubProjectFiles(project_repositories(infra_root), token)


# -- handshakes -------------------------------------------------------------------

#: Why a declared half has no edge, in the order they are checked.
PRODUCER_MISSING = "the producer does not list the consumer"
CONSUMER_MISSING = "the consumer does not read the dataset"
NOT_ONBOARDED = "the dataset is not onboarded"


@dataclass(frozen=True)
class Edge:
    """An agreed handshake: `consumer` reads `dataset`, read-only."""

    dataset: OnboardedDataset
    consumer: str
    #: Why, from the consumer's `reads`.
    purpose: str


@dataclass(frozen=True)
class Pending:
    """A handshake one side declared but that grants nothing yet, and why."""

    #: `<owner>/<name>`, onboarded or not.
    dataset: str
    producer: str
    consumer: str
    reason: str


@dataclass(frozen=True)
class Access:
    """Every edge and pending handshake among the files that were read."""

    edges: tuple[Edge, ...]
    pending: tuple[Pending, ...]

    def shared(self, owner: str, name: str) -> bool:
        """Whether some workspace reads `<owner>/<name>`: its role is then a bucket reader."""
        return any(e.dataset.owner == owner and e.dataset.name == name for e in self.edges)

    def consumed_by(self, consumer: str) -> tuple[Edge, ...]:
        """The edges `consumer` reads: its S3 endpoint's statements."""
        return tuple(e for e in self.edges if e.consumer == consumer)


def compute_access(registry: Sequence[OnboardedDataset], files: Mapping[str, SiteConfig]) -> Access:
    """The edges and pending handshakes among `files`, keyed by project.

    Only pairs whose producer's and consumer's files are both in `files` are
    judged: a project's own plan reads just its counterparts, and a file that
    could not be read has already failed (ProjectFiles), so a pair left out
    here is never taken for a revoked one. An onboarded dataset its owner's
    file does not declare, or whose prefix lies outside the component's, is an
    error naming its registry file.
    """
    onboarded = {d.id: d for d in registry}
    for d in registry:
        owner = files.get(d.owner)
        if owner is not None:
            _check_onboarding(d, owner)
    producer_halves: set[tuple[str, str]] = set()
    consumer_halves: dict[tuple[str, str], str] = {}
    for project, config in files.items():
        for component in config.components:
            if isinstance(component, Dataset):
                for consumer in component.consumers:
                    producer_halves.add((f"{project}/{component.name}", consumer))
            elif isinstance(component, DatabricksWorkspace):
                for read in component.reads:
                    consumer_halves[(read.dataset, project)] = read.purpose
    edges: list[Edge] = []
    pending: list[Pending] = []
    for dataset_id, consumer in sorted(producer_halves | set(consumer_halves)):
        producer = dataset_id.split("/", 1)[0]
        if producer not in files or consumer not in files:
            continue
        if (dataset_id, consumer) not in producer_halves:
            reason = PRODUCER_MISSING
        elif (dataset_id, consumer) not in consumer_halves:
            reason = CONSUMER_MISSING
        elif dataset_id not in onboarded:
            reason = NOT_ONBOARDED
        else:
            edges.append(
                Edge(onboarded[dataset_id], consumer, consumer_halves[(dataset_id, consumer)])
            )
            continue
        pending.append(Pending(dataset_id, producer, consumer, reason))
    return Access(edges=tuple(edges), pending=tuple(pending))


def _check_onboarding(dataset: OnboardedDataset, owner: SiteConfig) -> None:
    where = f"datasets/{dataset.owner}/{dataset.name}.yaml"
    component = next(
        (c for c in owner.components if isinstance(c, Dataset) and c.name == dataset.name), None
    )
    if component is None:
        raise ConfigError(
            f"{where}: {dataset.owner}'s file declares no dataset {dataset.name!r}, so there "
            "is nothing to onboard"
        )
    if not dataset.prefix.startswith(component.prefix):
        raise ConfigError(
            f"{where}: prefix {dataset.prefix!r} lies outside {component.prefix!r}, the prefix "
            f"of {dataset.owner}'s dataset {dataset.name}"
        )


def counterparts(config: SiteConfig) -> tuple[str, ...]:
    """The projects whose files complete this file's handshakes: its datasets'
    consumers and the owners of the datasets its workspaces read. Empty for a
    project that declares neither half, whose plan then reads no other file."""
    names: set[str] = set()
    for component in config.components:
        if isinstance(component, Dataset):
            names.update(component.consumers)
        elif isinstance(component, DatabricksWorkspace):
            names.update(read.dataset.split("/", 1)[0] for read in component.reads)
    names.discard(config.project)
    return tuple(sorted(names))


def access_for_project(
    config: SiteConfig, registry: Sequence[OnboardedDataset], files: ProjectFiles
) -> Access:
    """The handshakes of one project's plan: its own file as given (it may be a
    branch's), and each counterpart's from `files`. A counterpart that cannot be
    read raises; it is never treated as one without the other half."""
    loaded = {name: files.load(name) for name in counterparts(config)}
    loaded[config.project] = config
    return compute_access(registry, loaded)


def access_for_platform(
    registry: Sequence[OnboardedDataset], workspaces: Iterable[str], files: ProjectFiles
) -> Access:
    """Every handshake the reconcile applies: each Databricks workspace project's
    file, each onboarded dataset's owner's, and the owners its reads name."""
    loaded = {name: files.load(name) for name in sorted(set(workspaces))}
    owners = {d.owner for d in registry}
    for config in list(loaded.values()):
        owners.update(counterparts(config))
    for owner in sorted(owners - set(loaded)):
        loaded[owner] = files.load(owner)
    return compute_access(registry, loaded)
