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

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .components import check_prefixes
from .errors import ConfigError
from .settings import default_config_path

#: The longest `<owner>-<name>`: the key of the consumer endpoint's
#: `read_only_datasets` (databricks-workspace), stricter than IAM's 43
#: characters under `<organization>-ds-`.
ONBOARDING_KEY_MAX = 40
#: The infra checkout the registry and the project registries are read from.
ENV_INFRA_ROOT = "JES_INFRA_ROOT"
#: The one file in datasets/ that is not a dataset.
REGISTRY_README = "README.md"

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
