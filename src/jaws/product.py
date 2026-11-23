"""What a Jaws release owns: the Terraform version and the module family versions.

They live in `product.yaml` beside this module, which ships in the image, so a
platform's configuration (`config/`) cannot change them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

PRODUCT_FILE = Path(__file__).with_name("product.yaml")

#: The most bytes of a plan the tool puts in one pull request comment (GitHub's
#: limit is 65536 characters).
PLAN_COMMENT_MAX_BYTES = 60000

_FAMILY_ADDRESS = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[a-z0-9]+$")
_FAMILY_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class ProductPins:
    """The release's pins."""

    terraform_version: str
    #: Registry address to the one exact version every pin of that family carries.
    families: Mapping[str, str]


def load_product_pins(path: Path = PRODUCT_FILE) -> ProductPins:
    """Read and validate a release file; raises ConfigError if it is malformed."""
    try:
        raw: Any = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path}: cannot be read as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    terraform = raw.get("terraform")
    version = terraform.get("version") if isinstance(terraform, dict) else None
    if not isinstance(version, str) or not _FAMILY_VERSION.match(version):
        raise ConfigError(
            f"{path}: terraform.version must be an exact version such as 1.14.7, not {version!r}"
        )

    library = raw.get("library")
    families = library.get("families") if isinstance(library, dict) else None
    if not isinstance(families, dict) or not families:
        raise ConfigError(f"{path}: library.families must name at least one module family")
    for address, family_version in families.items():
        if not isinstance(address, str) or not _FAMILY_ADDRESS.match(address):
            raise ConfigError(
                f"{path}: library.families key {address!r} must be a registry address, "
                "<namespace>/<name>/<provider>"
            )
        if not isinstance(family_version, str) or not _FAMILY_VERSION.match(family_version):
            raise ConfigError(
                f"{path}: library.families[{address!r}] must be an exact version such as 0.1.0, "
                f"not {family_version!r}"
            )
    return ProductPins(terraform_version=version, families=dict(families))


@cache
def product_pins() -> ProductPins:
    """The pins of this release, read once."""
    return load_product_pins()
